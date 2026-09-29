// Run with Playwright available in NODE_PATH and the dashboard/Blender running.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const root = path.resolve(__dirname,'..');
const base = process.env.DASHBOARD_URL || 'http://127.0.0.1:8780';

(async()=>{
 const browser=await chromium.launch({headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1080}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const testName='Dashboard acceptance '+Date.now();
 try{
  await page.goto(base);
  await page.waitForFunction(()=>document.querySelector('#connectionLabel').textContent==='Blender connected');
  const before=await (await page.request.get(base+'/api/blender')).json();
  assert(before.ok);
  await page.click('#newSong');
  await page.fill('#newName',testName);
  await page.click('#newForm button[type=submit]');
  await page.waitForFunction(name=>document.querySelector('h1').textContent===name&&!document.querySelector('#chooseJson').disabled,testName);
  await page.setInputFiles('#jsonFile',path.join(root,'data/lesson_tests/12_complex_32_measures.json'));
  await page.waitForFunction(()=>document.querySelector('#message').textContent==='JSON imported and validated.');
  await page.setInputFiles('#wavFile',path.join(root,'outputs/complex_32_measures.wav'));
  await page.waitForFunction(()=>document.querySelector('#message').textContent==='WAV imported and validated.');
  const imported=await page.locator('#jsonName').innerText();
  await page.setInputFiles('#jsonFile',{name:'invalid.json',mimeType:'application/json',buffer:Buffer.from('{"version":2}')});
  await page.waitForFunction(()=>document.querySelector('#message').textContent.startsWith('Invalid JSON:'));
  assert.equal(await page.locator('#jsonName').innerText(),imported);
  await page.fill('#offset','0.25');await page.locator('#offset').blur();
  await page.waitForFunction(()=>!document.querySelector('#send').disabled);
  await page.click('#send');
  await page.waitForFunction(()=>document.querySelector('#message').textContent.startsWith('Lesson and audio applied'),{},{timeout:60000});
  const first=await (await page.request.get(base+'/api/blender')).json();
  assert.equal(first.layout_fingerprint,before.layout_fingerprint);
  assert.equal(first.audio_strips,1);assert.equal(first.markers,6);
  await page.click('#send');
  await page.waitForFunction(()=>document.querySelector('#message').textContent.startsWith('Lesson and audio applied'),{},{timeout:60000});
  const second=await (await page.request.get(base+'/api/blender')).json();
  assert.equal(second.audio_strips,1);assert.equal(second.markers,6);
  assert.equal(second.layout_fingerprint,before.layout_fingerprint);
  await page.click('button.song:has-text("32-measure guitar study")');
  await page.waitForFunction(()=>document.querySelector('h1').textContent==='32-measure guitar study'&&!document.querySelector('#send').disabled);
  await page.click('#send');
  await page.waitForFunction(()=>document.querySelector('#message').textContent.startsWith('Lesson and audio applied'),{},{timeout:60000});
  await page.click('#saveBlend');
  await page.waitForFunction(()=>document.querySelector('#message').textContent==='Blender file saved.');
  await page.evaluate(async()=>{await audio.play();});
  await page.waitForTimeout(700);
  assert(await page.evaluate(()=>audio.currentTime>0));
  await page.evaluate(()=>{audio.pause();audio.currentTime=0;});
  await page.waitForTimeout(300);
  await page.evaluate(()=>draw());
  const pixels=await page.evaluate(()=>['waveform','tablature'].map(id=>{
    const c=document.getElementById(id),data=c.getContext('2d').getImageData(0,0,c.width,c.height).data;
    const colors=new Set();for(let i=0;i<data.length;i+=4)colors.add(`${data[i]},${data[i+1]},${data[i+2]}`);return colors.size;
  }));
  assert(pixels.every(n=>n>8));
  await page.screenshot({path:'/tmp/guitar-dashboard-desktop-final.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});await page.waitForTimeout(300);await page.evaluate(()=>draw());
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:'/tmp/guitar-dashboard-mobile-final.png',fullPage:true});
  const rejected=await page.request.post(base+'/api/songs',{headers:{Origin:'http://untrusted.invalid'},data:{name:'Blocked'}});
  assert.equal(rejected.status(),403);
  assert.deepEqual(errors,[]);
  console.log('PASS: imports, invalid JSON preserved, audio offset, repeated sync, fixed transforms, scene saving, audio playback, canvas pixels, mobile layout, origin check.');
  console.log('TEST_SONG_ID='+first.song_id);
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
