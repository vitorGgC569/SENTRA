"use strict";
/* SENTRA Canvas Fractal Grid — original Canvas 2D adaptation of the interaction
 * concepts documented at cult-ui.com/docs/components/canvas-fractal-grid.
 * No React/Motion/shader downloads; safe for local CSP and Windows WebView2.
 */
(function (root) {
  const canvas = document.getElementById("fractal-grid");
  const viewport = document.getElementById("viewport");
  if (!canvas || !viewport) return;
  const ctx = canvas.getContext("2d", {alpha:false, desynchronized:true});
  if (!ctx) return;
  document.documentElement.classList.add("fractal-ready");
  const mq = root.matchMedia?.("(prefers-reduced-motion: reduce)");
  const dark = {
    background:"#11161d",
    shadow:"rgba(22,38,49,0.14)",
    teal:[106,178,183], blue:[108,142,185]
  };
  const settings = {spacing:27, dotRadius:.9, fps:28, maxDots:9500, enableGlow:true, enableNoise:true};
  let width=0,height=0,dpr=1,visible=true,raf=0,last=0,dirty=true;
  let camera={x:0,y:0,scale:1},pointer={x:0,y:0,active:false},time=0;
  const reduced=()=>Boolean(mq?.matches);
  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
  // Consistent hash noise avoids flickering/seeded global randomness.
  function noise(x,y){let k=Math.imul((x|0)^41939,374761393)+Math.imul((y|0)^17923,668265263);
    k=Math.imul(k^(k>>>13),1274126177);return ((k^(k>>>16))>>>0)/4294967295;}
  function resize(){
    const box=viewport.getBoundingClientRect();
    width=Math.max(0,Math.round(box.width));height=Math.max(0,Math.round(box.height));
    if (!width||!height)return;
    dpr=Math.min(root.devicePixelRatio||1,width*height>1600000?1:1.5);
    canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);
    canvas.style.width=width+"px";canvas.style.height=height+"px";
    ctx.setTransform(dpr,0,0,dpr,0,0);
    dirty=true;request();
  }
  function draw(now){
    raf=0;
    if(!visible||!width||!height)return;
    if(!dirty&&!reduced()&&now-last<1000/settings.fps){request();return;}
    last=now;dirty=false;
    if(!reduced())time=now/1000;
    ctx.fillStyle=dark.background;
    ctx.fillRect(0,0,width,height);
    const ambient=ctx.createRadialGradient(width*.58,height*.41,30,width*.58,height*.41,Math.max(width,height)*.85);
    ambient.addColorStop(0,"rgba(28,48,59,.47)");
    ambient.addColorStop(.62,"rgba(17,30,42,.20)");
    ambient.addColorStop(1,"rgba(8,13,20,.02)");
    ctx.fillStyle=ambient;ctx.fillRect(0,0,width,height);
    // Mouse light stays faint; never obscure graph labels or PTY glyphs.
    if(settings.enableGlow && pointer.active && !reduced()){
      const glow=ctx.createRadialGradient(pointer.x,pointer.y,4,pointer.x,pointer.y,235);
      glow.addColorStop(0,"rgba(85,150,157,.115)");
      glow.addColorStop(.52,"rgba(54,111,137,.048)");
      glow.addColorStop(1,"rgba(32,73,90,0)");
      ctx.fillStyle=glow;ctx.fillRect(pointer.x-240,pointer.y-240,480,480);
    }
    const pitch=clamp(settings.spacing*camera.scale,19,43);
    const offsetX=((camera.x%pitch)+pitch)%pitch,offsetY=((camera.y%pitch)+pitch)%pitch;
    const nx=Math.ceil(width/pitch)+1,ny=Math.ceil(height/pitch)+1;
    const stride=Math.max(1,Math.ceil(Math.sqrt(nx*ny/settings.maxDots)));
    const phase=reduced()?0:time*.33;
    const primary=dark.teal,secondary=dark.blue;
    for(let iy=0;iy<ny;iy+=stride){
      const y=offsetY+iy*pitch;
      for(let ix=0;ix<nx;ix+=stride){
        const x=offsetX+ix*pitch;
        const radial=Math.hypot((x-width*.55)/Math.max(width,1),(y-height*.45)/Math.max(height,1));
        const wave=Math.sin(ix*.21+phase)+Math.cos(iy*.23-phase*.73)+Math.sin((ix+iy)*.09-phase*.49);
        const flicker=noise(ix,iy);
        let opacity=clamp(.10 + wave*.025 + (1-radial)*.07 + flicker*.03,.055,.26);
        const dist=pointer.active&&!reduced()?Math.hypot(x-pointer.x,y-pointer.y):Infinity;
        if(dist<175)opacity+=.21*Math.pow(1-dist/175,2);
        const rgb=(ix+iy)%7===0?secondary:primary;
        ctx.beginPath();ctx.arc(x,y,settings.dotRadius+(dist<90?.17:0),0,Math.PI*2);
        ctx.fillStyle="rgba("+rgb.join(",")+","+opacity.toFixed(3)+")";
        ctx.fill();
      }
    }
    if(settings.enableNoise){
      ctx.fillStyle="rgba(183,205,215,.018)";
      for(let i=0;i<Math.min(150,Math.floor(width*height/6500));i++){
        const px=noise(i,439)*width,py=noise(i,911)*height;
        ctx.fillRect(px,py,.65,.65);
      }
    }
    if(!reduced())request();
  }
  function request(){if(!raf&&visible&&width&&height)raf=root.requestAnimationFrame(draw);}
  function setCamera(x,y,scale){
    const next={x:Number(x)||0,y:Number(y)||0,scale:clamp(Number(scale)||1,.28,2.25)};
    if(next.x!==camera.x||next.y!==camera.y||next.scale!==camera.scale){
      camera=next;dirty=true;request();
    }
  }
  function onPointer(e){
    const rect=viewport.getBoundingClientRect();
    pointer={x:e.clientX-rect.left,y:e.clientY-rect.top,active:true};
    dirty=true;request();
  }
  function onVisibility(){visible=!document.hidden;if(visible){dirty=true;request();}else if(raf){root.cancelAnimationFrame(raf);raf=0;}}
  viewport.addEventListener("pointermove",onPointer,{passive:true});
  viewport.addEventListener("pointerleave",()=>{pointer.active=false;dirty=true;request();},{passive:true});
  document.addEventListener("visibilitychange",onVisibility);
  mq?.addEventListener?.("change",()=>{dirty=true;request();});
  const observer=new ResizeObserver(resize);observer.observe(viewport);
  root.addEventListener("resize",resize,{passive:true});
  resize();
  root.SentraFractalGrid=Object.freeze({setCamera,settings:Object.freeze({...settings})});
})(window);
