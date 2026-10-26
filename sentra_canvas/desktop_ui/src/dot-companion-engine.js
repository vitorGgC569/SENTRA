/*!
 * SENTRA animated Dot companions.
 * Drawing and character data adapted from the user's local
 * docs/design/mini-companions.html. No gallery markup, cards or backgrounds are imported.
 * The host remains authoritative for task state and completion.
 */
const TAU=Math.PI*2,clamp=(v,a,b)=>Math.max(a,Math.min(b,v)),R=Math.random;
const V=[
{n:'Pudim',t:'Doce, trêmulo e sempre no ponto.',c:'#FFD05A',c2:'#F5A524',nn:3.3,w:.8,h:.6,ey:.68,d:'pudim',ink:'#4a2a12'},
{n:'Nuvem',t:'Flutua por aí e adora uma soneca.',c:'#F4F8FF',c2:'#B7D0F2',nn:2.7,w:.86,h:.5,ey:.95,d:'nuvem',ink:'#22345a'},
{n:'Broto',t:'Cresce um pouquinho a cada commit.',c:'#9AE893',c2:'#4CC06E',nn:3.4,w:.7,h:.62,ey:.85,d:'broto',ink:'#14391f'},
{n:'Brasa',t:'Esquenta quando o build quebra.',c:'#FF9A66',c2:'#EC5A44',nn:3.1,w:.74,h:.6,ey:.85,d:'brasa',ink:'#4a1710'},
{n:'Gotinha',t:'Curiosa, transparente e escorregadia.',c:'#86D4FF',c2:'#3E9CF0',nn:2.3,w:.62,h:.7,ey:.62,d:'gota',ink:'#0f2f5a'},
{n:'Cacto',t:'Espinhoso por fora, fofo por dentro.',c:'#BDE57F',c2:'#7DC25A',nn:3.4,w:.5,h:.7,ey:.9,d:'cacto',ink:'#243d15'},
{n:'Miau',t:'Silencioso, curioso e sempre no teclado.',c:'#CDBBFF',c2:'#9B83EA',nn:3,w:.74,h:.6,ey:.8,d:'gato',ink:'#2b1d5a'},
{n:'Queijinho',t:'Quentinho, macio e impossível comer um só.',c:'#FFE08A',c2:'#E9A93C',nn:2.4,w:.74,h:.62,ey:.8,d:'queijo',ink:'#5a3410'},
{n:'Algodão',t:'Macio como nuvem de açúcar, sempre de orelha em pé.',c:'#FFF1F7',c2:'#F3C3DA',nn:2.6,w:.72,h:.56,ey:.8,d:'coelho',ink:'#5a3a55'},
{n:'Lua',t:'Doce, luminosa e sempre por perto, para quem ilumina as suas noites.',c:'#FFF3C4',c2:'#F2CF72',nn:2.15,w:.64,h:.64,ey:.71,fx:-.31,fs:.7,cs:.72,es:.92,d:'lua',ink:'#2a2350',hero:1},
{sec:1,n:'Tesla',t:'Faíscas na cabeça e corrente alternada no coração.',c:'#BFD0FF',c2:'#6F86F0',nn:3,w:.74,h:.54,ey:.8,d:'tesla',ink:'#1d2350',pt:['⚡','AC'],pc:'#E0A800'},
{n:'Einstein',t:'Cabelo no caos, ideias em perfeita ordem. Relatividade em modo fofo.',c:'#FFE2CB',c2:'#F4B995',nn:2.6,w:.72,h:.62,ey:.82,d:'einstein',ink:'#3a2a22',pt:['E=mc²','c²','∞'],pc:'#5B4BC4'},
{n:'Turing',t:'Pensa em zeros e uns, e perguntou se máquinas podem pensar.',c:'#9BE0D3',c2:'#45B3A6',nn:3.2,w:.72,h:.62,ey:.85,d:'turing',ink:'#12332f',pt:['0','1','01','10'],pc:'#1F8A7E'},
{n:'Ada Lovelace',t:'Viu que máquinas podiam fazer mais do que contas.',c:'#FFD3EC',c2:'#E58FCB',nn:2.9,w:.7,h:.62,ey:.85,d:'ada',ink:'#4a1d44',pt:['⚙','λ','∑'],pc:'#C0489D'},
{n:'Grace Hopper',t:'Pioneira dos compiladores e do COBOL, com pose de comandante.',c:'#CFE0FF',c2:'#7BA2EA',nn:3,w:.74,h:.6,ey:.8,d:'grace',ink:'#14264d',pt:['🐛','COBOL','{ }'],pc:'#2F56B5'},
{n:'Marie Curie',t:'Descobriu o rádio e o polônio, e brilha no escuro.',c:'#C8F5B8',c2:'#62D08C',nn:2.6,w:.7,h:.62,ey:.85,d:'curie',ink:'#173b24',pt:['Ra','Po','✦'],pc:'#2AA35A'},
{n:'Oxta',t:'Observa em silêncio, de óculos redondos e capuz. Julga o seu código com carinho.',c:'#F7A85C',c2:'#E27B30',nn:3,w:.66,h:.58,ey:.9,fs:.9,d:'capuz',ink:'#2b1a10',lid:.32,cs:.6,hero2:1,pt:['🐾','👓','z'],pc:'#6b5a48'}];
let px=null,py=null,lastMove=0;
let mounted=0;
function trackPointer(e){px=e.clientX;py=e.clientY;lastMove=performance.now();}
function listenPointer(){if(++mounted===1)window.addEventListener('pointermove',trackPointer,{passive:true});}
function unlistenPointer(){if(--mounted===0)window.removeEventListener('pointermove',trackPointer);}


class Mini{
constructor(v,canvas){
 this.v=v;this.cv=canvas;this.x=this.cv.getContext('2d');
 Object.assign(this,{lx:0,ly:0,s:0,sv:0,jy:0,vy:0,jc:0,dy:0,rot:0,hv:0,hov:false,bl:0,bs:-10,nb:1+R()*2,mood:'idle',until:0,act:performance.now(),clicks:[],pt:[],acc:0,seed:R()*10});
 this.cv.addEventListener('pointerenter',()=>{this.hov=true;this.act=performance.now();if(this.mood==='sleep')this.set('hello',1400)});
 this.cv.addEventListener('pointerleave',()=>this.hov=false);
 this.cv.addEventListener('pointerdown',()=>this.poke());
 this.observer=new ResizeObserver(()=>this.resize());this.observer.observe(this.cv);this.resize();
}
resize(){
 const bounds=this.cv.getBoundingClientRect();
 // clientWidth is the untransformed CSS size; bounding rect includes Home's rotation.
 const size=Math.max(1,Math.min(this.cv.clientWidth||bounds.width,this.cv.clientHeight||bounds.height));
 // Supersample even on 100%-scale monitors to keep rounded faces and fine details crisp.
 const d=Math.min(3,Math.max(2,window.devicePixelRatio||1));
 const pixels=Math.round(size*d);
 if(this.cv.width!==pixels||this.cv.height!==pixels){
  this.cv.width=pixels;this.cv.height=pixels;
 }
 this.S=size;this.d=pixels/size;
}
set(m,ms){const n=performance.now();this.mood=m;this.until=n+ms;this.act=n;this.jc=m==='hello'?2:m==='happy'?3:m==='done'?2:0;if(m==='annoyed')this.sv=-4;if(this.jc)this.hop()}
hop(){if(this.jy===0){this.vy=1.3;this.sv=3}}
poke(){const n=performance.now();this.act=n;this.clicks=this.clicks.filter(c=>n-c<1200);this.clicks.push(n);
 if(this.mood==='sleep'){this.set('hello',1400);this.clicks=[];return}
 if(this.clicks.length>=3){this.clicks=[];this.set('dizzy',3500)}else this.set('annoyed',1300)}
step(dt,t,n){
 const k=1-Math.exp(-dt*9);let m=this.mood;
 if(m!=='idle'&&m!=='sleep'&&n>this.until){this.mood=m=this.baseMood||'idle';this.act=n}
 if(m==='idle'&&n-this.act>30000)this.set('sleep',1e12);
 let tx,ty;const r=this.cv.getBoundingClientRect();
 if(m==='sleep'){tx=0;ty=.6}
 else if(m==='dizzy'){tx=Math.sin(t*5)*.6;ty=Math.cos(t*5)*.4}
 else if(m==='think'){tx=.75;ty=-.75}
 else if(m==='work'){tx=Math.sin(t*3)*.8;ty=.35}
 else if(m==='listen'||m==='speak'){tx=0;ty=0}
 else if(m==='wait'){tx=Math.sin(t*.9)>.85?.7:0;ty=.1}
 else if(m==='error'){tx=Math.sin(t*14)*.3;ty=.2}
 else if(px!==null&&n-lastMove<5000){tx=clamp((px-(r.left+r.width/2))/(r.width*1.1),-1,1);ty=clamp((py-(r.top+r.height*.6))/(r.height*1.1),-1,1)}
 else{tx=Math.sin(t*.5+this.seed)*.6;ty=.1+Math.sin(t*.37+this.seed*2)*.3}
 this.lx+=(tx-this.lx)*k;this.ly+=(ty-this.ly)*k;
 this.hv+=((this.hov&&m!=='sleep'?1:0)-this.hv)*k;
 if(t>this.nb){this.bs=t;this.nb=t+2+R()*3.5}
 const bp=(t-this.bs)/.16;this.bl=bp>=0&&bp<=1?Math.sin(bp*Math.PI):0;
 this.sv+=(-190*this.s-12*this.sv)*dt;this.s+=this.sv*dt;
 if(this.jy>0||this.vy!==0){this.vy-=8*dt;this.jy+=this.vy*dt;
  if(this.jy<=0){this.jy=0;const f=this.vy<-.4;this.vy=0;if(f){this.sv=-3;if(this.jc>0&&--this.jc>0)this.hop()}}}
 let rt=0;this.dy=0;
 if(m==='dance'){this.dy=Math.abs(Math.sin(t*4))*.04;rt=Math.sin(t*4)*.12}
 if(m==='dizzy')rt=Math.sin(t*6)*.1;
 if(this.v.d==='lua'&&m!=='dance')this.dy=(.5+.5*Math.sin(t*1.3))*.025;
 if(this.v.pt&&(m==='hello'||m==='happy')&&this.acc>.35){this.acc=0;this.spawn(this.v.pt[Math.floor(R()*this.v.pt.length)],this.v.pc)}
 if(m==='think')rt=Math.sin(t*1.6)*.06+.05;
 if(m==='listen')rt=Math.sin(t*1.2)*.07;
 if(m==='speak')this.dy+=Math.abs(Math.sin(t*9))*.012;
 if(m==='work')this.dy+=Math.abs(Math.sin(t*14))*.008;
 if(m==='wait'&&(t%1.4)<dt)this.sv=-2.2;
 if(m==='error')rt=Math.sin(t*28)*.1*clamp((this.until-n)/2500,0,1);
 if(m==='done'&&this.acc>.12){this.acc=0;this.spawn('✦','#FFC93C')}
 this.rot+=(rt-this.rot)*k;
 this.acc+=dt;
 if(m==='dance'&&this.acc>.4){this.acc=0;this.spawn(R()<.5?'♪':'♫','#ff6fa5')}
 if(m==='sleep'&&this.acc>1.5){this.acc=0;this.spawn('z',this.v.d==='lua'?'#cfd6ff':this.v.ink)}
 if(this.v.d==='lua'&&(m==='hello'||m==='happy')&&this.acc>.22){this.acc=0;this.spawn('♥','#ff7fae')}
 this.pt=this.pt.filter(p=>(p.l-=dt*.8)>0);this.pt.forEach(p=>{p.x+=p.vx*dt;p.y+=p.vy*dt});
}
spawn(ch,col){const S=this.S;this.pt.push({x:S/2+(R()-.3)*S*.3,y:S*.88-this.v.h*S*.85,vx:(R()-.3)*S*.06,vy:-S*.065,l:1,ch,col})}
cres(x,R){const f=-.75,d=.82*R,ri=.8*R,cx=d*Math.cos(f),cy=-R+d*Math.sin(f),al=Math.acos((R*R+d*d-ri*ri)/(2*R*d)),be=Math.acos((ri*ri+d*d-R*R)/(2*ri*d));x.beginPath();x.arc(0,-R,R,f+al,f+TAU-al,false);x.arc(cx,cy,ri,f+Math.PI+be,f+Math.PI-be,true);x.closePath()}
path(x,a,b){const N=72,v=this.v;if(v.d==='lua')return this.cres(x,Math.min(a,b));x.beginPath();
 for(let i=0;i<=N;i++){const th=i/N*TAU,c=Math.cos(th),s=Math.sin(th);
  let X=a*Math.sign(c)*Math.abs(c)**(2/v.nn),Y=b*Math.sign(s)*Math.abs(s)**(2/v.nn);
  if(v.d==='gota'){const u=Math.max(0,-Y/b);X*=1-.88*u**1.8}
  x[i?'lineTo':'moveTo'](X,Y-b)}x.closePath()}
draw(t){
 const x=this.x,S=this.S,v=this.v,a=v.w*S/2,b=v.h*S/2,g=S*.88,m=this.mood,jh=this.jy+this.dy;
 if(!S)return;
 x.setTransform(this.d,0,0,this.d,0,0);x.clearRect(0,0,S,S);if(v.d==='lua')this.sky(x,S,t);
 x.fillStyle='rgba(0,0,0,'+Math.max(.04,.16-jh*.5)+')';x.beginPath();x.ellipse(S/2,g+S*.012,a*(v.d==='capuz'?1.05:.8)*(1-jh*1.2),S*.03,0,0,TAU);x.fill();
 if(v.d==='gota'){const q=(t%2)/2;x.strokeStyle='rgba(62,156,240,'+(.35*(1-q))+')';x.lineWidth=2;x.beginPath();x.ellipse(S/2,g+S*.012,a*(.7+q*.6),S*.03+q*S*.02,0,0,TAU);x.stroke()}
 x.save();x.translate(S/2,g-jh*S);x.rotate(this.rot);
 const br=Math.sin(t*(m==='sleep'?1.2:2.4))*.012;x.scale(1-this.s*.6-br*.6,1+this.s+br);
 // back decorations
 if(v.d==='coelho'){const e=Math.sin(t*2.2)*.04;[-1,1].forEach(s=>{x.save();x.translate(s*.42*a,-1.9*b);x.rotate(s*(.18+e));x.fillStyle=v.c;x.beginPath();x.ellipse(0,-.38*b,.2*a,.45*b,0,0,TAU);x.fill();x.fillStyle='#FFB3CF';x.beginPath();x.ellipse(0,-.38*b,.1*a,.3*b,0,0,TAU);x.fill();x.restore()})}
 if(v.d==='tesla'){this.glow(x,a,b,'130,160,255',t);x.strokeStyle='#FFF08A';x.lineWidth=b*.035;x.lineCap='round';x.lineJoin='round';const n=m==='annoyed'||m==='happy'?5:3,f=Math.floor(t*12);
  for(let i=0;i<n;i++){const sd=f*7+i*13,an=-Math.PI/2+Math.sin(sd*12.9)*1.5;let X=0,Y=-2.24*b;x.beginPath();x.moveTo(X,Y);for(let k=1;k<=4;k++){X+=Math.cos(an)*b*.16+Math.sin(sd*k*3.1)*b*.09;Y+=Math.sin(an)*b*.12+Math.cos(sd*k*2.3)*b*.06;x.lineTo(X,Y)}x.stroke()}}
 if(v.d==='einstein'){[['#CFD1E6',0],['#F6F6FB',-.03]].forEach(p=>{x.fillStyle=p[0];for(let i=0;i<9;i++){const an=Math.PI*(1+i*.125),w=Math.sin(t*2+i)*.04;x.beginPath();x.arc(Math.cos(an)*a,-b+Math.sin(an)*b*1.02,b*(.3+w+(i%2)*.06+p[1]),0,TAU);x.fill()}})}
 if(v.d==='ada'){x.fillStyle='#6b4430';[-1,1].forEach(s=>[0,1,2].forEach(k=>{x.beginPath();x.arc(s*a*(.98+Math.sin(t*2+k)*.02),-b*1.35+k*.38*b,b*.2,0,TAU);x.fill()}))}
 if(v.d==='curie'){this.glow(x,a,b,'110,240,150',t);x.fillStyle='#5a3b2a';x.beginPath();x.arc(0,-2.08*b,b*.3,0,TAU);x.fill()}
 if(v.d==='lua'){const hg=x.createRadialGradient(0,-b,a*.7,0,-b,a*1.42);hg.addColorStop(0,'rgba(255,226,140,'+(.38+.08*Math.sin(t*1.6))+')');hg.addColorStop(1,'rgba(255,226,140,0)');x.fillStyle=hg;x.beginPath();x.arc(0,-b,a*1.42,0,TAU);x.fill()}
 if(v.d==='gato'){x.fillStyle=v.c;x.strokeStyle=v.c;x.lineWidth=b*.14;x.lineJoin='round';const fl=Math.max(0,Math.sin(t*3.1))**8*.1*b;
  [-1,1].forEach(s=>{const f=s<0?fl:0;x.beginPath();x.moveTo(s*.85*a,-1.45*b);x.lineTo(s*.66*a,-2.3*b-f);x.lineTo(s*.2*a,-1.9*b);x.closePath();x.fill();x.stroke();x.fillStyle='#FFB3CF';x.beginPath();x.moveTo(s*.72*a,-1.65*b);x.lineTo(s*.64*a,-2.05*b-f);x.lineTo(s*.42*a,-1.85*b);x.closePath();x.fill();x.fillStyle=v.c});
  x.strokeStyle=v.c2;x.lineWidth=b*.17;x.lineCap='round';const tw=Math.sin(t*3)*b*.1;x.beginPath();x.moveTo(a*.7,-b*.25);x.quadraticCurveTo(a*1.22,-b*.2+tw,a*1.15,-b*.9+tw*1.2);x.stroke()}
 if(v.d==='nuvem'){x.fillStyle=v.c;const w=Math.sin(t*1.6)*.03;
  [[-.38*a,-1.9*b,.46*b],[.1*a,-2.08*b,.58*b+w*b],[.5*a,-1.88*b,.4*b]].forEach(c=>{x.beginPath();x.arc(c[0],c[1],c[2],0,TAU);x.fill()})}
 if(v.d==='brasa'){const big=m==='annoyed'?1.5:1;
  [[-.35*a,.55,.22,0],[0,.9,.3,1.7],[.35*a,.6,.22,3.1]].forEach(f=>{
   [['#FF7A3D',1],['#FFD166',.55]].forEach(o=>this.flame(x,f[0],-2*b+.15*b,b*f[1]*o[1]*big*(1+Math.sin(t*9+f[3])*.08),b*f[2]*o[1],o[0],Math.sin(t*7+f[3])*b*.1))})}
 if(v.d==='cacto'){x.strokeStyle=v.c2;x.lineWidth=b*.26;x.lineCap='round';x.lineJoin='round';
  const w=m==='hello'||m==='happy'?Math.sin(t*10)*.08*b:0;
  x.beginPath();x.moveTo(-a*.8,-b*1.1);x.lineTo(-a*1.18,-b*1.1);x.lineTo(-a*1.18,-b*1.55+w);
  x.moveTo(a*.8,-b*.9);x.lineTo(a*1.18,-b*.9);x.lineTo(a*1.18,-b*1.3-w);x.stroke()}
 // body
 const gr=x.createLinearGradient(0,-2*b,0,0);gr.addColorStop(0,v.c);gr.addColorStop(1,v.c2);
 this.path(x,a,b);x.fillStyle=gr;x.globalAlpha=v.d==='gota'?.93:1;x.fill();x.globalAlpha=1;if(v.d==='lua'){x.strokeStyle=gr;x.lineWidth=a*.2;x.lineJoin='round';x.stroke()}
 x.save();x.clip();
 x.fillStyle='rgba(255,255,255,.3)';x.beginPath();x.ellipse(-a*.42,-b*1.5,a*.22,b*.11,-.5,0,TAU);x.fill();
 x.fillStyle='rgba(0,0,0,.06)';x.beginPath();x.ellipse(0,0,a*1.1,b*.35,0,0,TAU);x.fill();
 x.fillStyle='rgba(255,255,255,.55)';x.beginPath();x.arc(-a*.66,-b*1.32,b*.035,0,TAU);x.fill();this.path(x,a,b);x.strokeStyle='rgba(255,255,255,.22)';x.lineWidth=b*.07;x.stroke();
 if(v.d==='pudim'){
  const cg=x.createLinearGradient(0,-2*b,0,-1.4*b);cg.addColorStop(0,'#C46F2F');cg.addColorStop(1,'#7A3B16');
  x.fillStyle=cg;x.beginPath();x.moveTo(-a-5,-2*b-5);x.lineTo(a+5,-2*b-5);
  for(let i=0;i<=40;i++){const q=i/40;x.lineTo(a-2*a*q,-2*b+.34*b+(.5+.5*Math.sin(q*TAU*2.5+.8))*.2*b)}
  x.closePath();x.fill();
  x.fillStyle='rgba(255,255,255,.28)';x.beginPath();x.ellipse(-a*.3,-1.85*b,a*.3,b*.05,-.05,0,TAU);x.fill()}
 x.restore();
 if(v.d==='lua'||v.d==='queijo'){x.save();this.path(x,a,b);x.clip();
  if(v.d==='queijo')[[-.6,-.5,.11],[.64,-.45,.09],[.5,-1.5,.1],[-.55,-1.5,.08],[.05,-.12,.07],[-.1,-1.8,.07]].forEach(c=>{x.fillStyle='rgba(176,104,22,.28)';x.beginPath();x.ellipse(c[0]*a,c[1]*b,c[2]*a,c[2]*a*.8,0,0,TAU);x.fill()});
  else{const f=-.75,e=(an,r)=>[Math.cos(an)*r*a,-b+Math.sin(an)*r*a];
   [[f+Math.PI-1.25,.8,.12],[f+Math.PI+1.2,.8,.1],[4.2,.85,.07]].forEach(c=>{const q=e(c[0],c[1]);x.fillStyle='rgba(205,160,60,.24)';x.beginPath();x.ellipse(q[0],q[1],c[2]*a,c[2]*a*.85,0,0,TAU);x.fill();x.fillStyle='rgba(255,255,255,.35)';x.beginPath();x.ellipse(q[0]-c[2]*a*.15,q[1]-c[2]*a*.2,c[2]*a*.6,c[2]*a*.45,0,0,TAU);x.fill()});
   const c1x=.82*a*Math.cos(f),c1y=-b+.82*a*Math.sin(f),rg=x.createRadialGradient(c1x,c1y,a*.78,c1x,c1y,a*1.35);rg.addColorStop(0,'rgba(214,160,70,.42)');rg.addColorStop(1,'rgba(214,160,70,0)');x.fillStyle=rg;x.fillRect(-2*a,-3*a,4*a,4*a)}
  x.restore()}
 // front decorations
 if(v.d==='pudim'){x.strokeStyle='#3d7a2a';x.lineWidth=b*.04;x.beginPath();x.moveTo(a*.02,-2*b);x.quadraticCurveTo(a*.1,-2.25*b,a*.22,-2.3*b);x.stroke();
  x.fillStyle='#E23A4B';x.beginPath();x.arc(0,-2*b-b*.05,b*.16,0,TAU);x.fill();x.fillStyle='rgba(255,255,255,.7)';x.beginPath();x.arc(-b*.06,-2*b-b*.1,b*.04,0,TAU);x.fill()}
 if(v.d==='broto'){const f=m==='happy'||m==='hello'||m==='dance'?9:2.2,sw=Math.sin(t*f)*b*.06,top=-2*b-b*.32;
  x.strokeStyle='#2E9A4C';x.lineWidth=b*.06;x.lineCap='round';x.beginPath();x.moveTo(0,-2*b+b*.05);x.quadraticCurveTo(sw,-2*b-b*.15,sw*1.5,top);x.stroke();
  [-1,1].forEach(s=>{x.fillStyle=s<0?'#3FAE5A':'#6BD47F';x.beginPath();x.ellipse(sw*1.5+s*b*.22,top-b*.03,b*.26,b*.12,s*(.55+Math.sin(t*f)*.12),0,TAU);x.fill()})}
 if(v.d==='gota'){x.fillStyle='rgba(255,255,255,.6)';x.beginPath();x.ellipse(-a*.38,-b*1.35,a*.1,b*.2,.45,0,TAU);x.fill()}
 if(v.d==='cacto'){x.strokeStyle='rgba(255,255,255,.7)';x.lineWidth=b*.025;x.lineCap='round';
  [[-.55,-1.5],[.6,-1.45],[-.65,-.35],[.62,-.4],[0,-.15]].forEach(p=>{const X=p[0]*a,Y=p[1]*b;x.beginPath();x.moveTo(X-b*.05,Y-b*.05);x.lineTo(X,Y);x.lineTo(X+b*.05,Y-b*.05);x.stroke()});
  const ry=-2*b-b*.07;x.fillStyle='#FF7FB0';for(let i=0;i<5;i++){const an=i/5*TAU+t*.5;x.beginPath();x.arc(Math.cos(an)*b*.13,ry+Math.sin(an)*b*.13,b*.09,0,TAU);x.fill()}
  x.fillStyle='#FFD34E';x.beginPath();x.arc(0,ry,b*.07,0,TAU);x.fill()}
 if(v.d==='gato'){x.strokeStyle='rgba(43,29,90,.45)';x.lineWidth=b*.025;x.lineCap='round';[-1,1].forEach(s=>[-.08,.08].forEach(k=>{x.beginPath();x.moveTo(s*a*.9,-.62*b+k*b);x.lineTo(s*a*1.12,-.62*b+k*b*2.2);x.stroke()}))}
 if(v.d==='queijo'){x.strokeStyle='rgba(255,255,255,.6)';x.lineWidth=b*.05;x.lineCap='round';[-.3,.25].forEach((o,i)=>{x.beginPath();for(let k=0;k<=12;k++){const q=k/12;x[k?'lineTo':'moveTo'](o*a+Math.sin(t*2+i*2+q*5)*b*.06,-2*b-b*.05-q*b*.4)}x.stroke()})}
 if(v.d==='tesla'){x.fillStyle='#6272D8';[0,1,2].forEach(k=>{x.beginPath();x.ellipse(0,-2*b-k*.07*b,(.3-k*.06)*a,.055*b,0,0,TAU);x.fill()});x.fillStyle='#E8ECFF';x.beginPath();x.arc(0,-2.24*b,.13*b,0,TAU);x.fill()}
 if(v.d==='turing')this.hair(x,a,b,'#2d3a4f',-1.74,1,1.5);
 if(v.d==='ada'||v.d==='curie'){const ad=v.d==='ada';this.hair(x,a,b,ad?'#6b4430':'#5a3b2a',ad?-1.72:-1.74,ad?0:-.4,2);
  if(ad){x.strokeStyle='rgba(0,0,0,.25)';x.lineWidth=b*.03;x.beginPath();x.moveTo(0,-2*b);x.lineTo(0,-1.72*b);x.stroke();x.fillStyle='#FF7FB0';[-1,1].forEach(s=>{x.beginPath();x.ellipse(-a*.5+s*b*.14,-1.92*b,b*.15,b*.09,s*.5,0,TAU);x.fill()});x.beginPath();x.arc(-a*.5,-1.92*b,b*.07,0,TAU);x.fill()}}
 if(v.d==='grace'){x.fillStyle='#F6F7FB';x.strokeStyle='#C9CFE3';x.lineWidth=b*.03;x.beginPath();x.ellipse(0,-1.55*b,.98*a,.62*b,0,Math.PI,TAU);x.closePath();x.fill();x.stroke();x.fillStyle='#14203a';x.beginPath();x.ellipse(0,-1.55*b,.98*a,.14*b,0,0,TAU);x.fill();x.beginPath();x.ellipse(0,-1.47*b,.7*a,.2*b,0,0,Math.PI);x.fill();x.fillStyle='#F5C84B';x.beginPath();x.arc(0,-1.9*b,.1*b,0,TAU);x.fill()}
 if(v.d==='capuz'){const hg=x.createLinearGradient(0,-2.7*b,0,0);hg.addColorStop(0,'#3a3330');hg.addColorStop(1,'#0d0b0a');x.fillStyle=hg;x.beginPath();this.hoodp(x,a,b);this.hole(x,a,b);x.fill('evenodd');
  x.strokeStyle='rgba(0,0,0,.25)';x.lineWidth=b*.09;x.beginPath();this.hole(x,a,b);x.stroke();
  x.strokeStyle='rgba(255,255,255,.1)';x.lineWidth=b*.05;x.lineCap='round';x.beginPath();x.moveTo(-.95*a,-1.4*b);x.bezierCurveTo(-.92*a,-1.95*b,-.55*a,-2.2*b,-.1*a,-2.28*b);x.stroke()}
 this.face(x,a,b,t);
 {const yw=this.lx*.55,Rr=Math.max(a*.23,b*.19)*(1+.14*this.hv),mx=a*Math.sin(yw)*.8,sy=-b*v.ey+this.ly*b*.14+Rr*1.2;
  if(v.d==='tesla')this.stache(x,mx,sy,Rr*1.4,Rr*.2,'#2b2a45');
  if(v.d==='einstein')this.stache(x,mx,sy,Rr*1.5,Rr*.5,'#E6E7F2')}
 if(v.d==='lua')this.moonstar(x,a,t);
 x.restore();
 // overlays
 if(m==='dizzy'){x.fillStyle='#FFC93C';x.font='bold '+S*.07+'px sans-serif';x.textAlign='center';x.textBaseline='middle';
  for(let i=0;i<3;i++){const an=t*4+i*TAU/3;x.fillText('✦',S/2+Math.cos(an)*a*.6,g-v.h*S-S*.05+Math.sin(an)*S*.03)}}
 this.status(x,S,a,t);this.pt.forEach(p=>{x.globalAlpha=Math.min(1,p.l*1.5);x.fillStyle=p.col;x.font='bold '+S*.075*(p.ch==='z'?.9:1)+'px sans-serif';x.textAlign='center';x.fillText(p.ch,p.x,p.y)});x.globalAlpha=1;
}
status(x,S,a,t){const m=this.mood,bx=S*.78,by=S*.2,V='#7c6cf0',rr=(...q)=>(x.roundRect||x.rect).apply(x,q);
 x.save();x.lineCap='round';x.fillStyle='rgba(255,255,255,.96)';x.strokeStyle='rgba(0,0,0,.12)';x.lineWidth=1.5;
 if(m==='think'){[[.66,.36,.012],[.7,.3,.018]].forEach(c=>{x.beginPath();x.arc(S*c[0],S*c[1],S*c[2],0,TAU);x.fill();x.stroke()});x.beginPath();x.ellipse(bx,by,S*.13,S*.085,0,0,TAU);x.fill();x.stroke();for(let i=-1;i<2;i++){x.fillStyle='#6b6478';x.beginPath();x.arc(bx+i*S*.06,by,S*.016*(.6+.7*Math.max(0,Math.sin(t*5-i*1.3))),0,TAU);x.fill()}}
 else if(m==='speak'){x.beginPath();rr(bx-S*.15,by-S*.085,S*.3,S*.17,S*.04);x.fill();x.stroke();x.beginPath();x.moveTo(bx-S*.1,by+S*.08);x.lineTo(bx-S*.14,by+S*.14);x.lineTo(bx-S*.05,by+S*.08);x.fill();const p=(t*1.2)%3.6;
  for(let i=0;i<3;i++){const w=clamp(p-i*1.1,0,1)*S*.2;x.fillStyle='#b9b4c8';x.fillRect(bx-S*.1,by-S*.05+i*S*.04,w,S*.014);if(w>0&&w<S*.2&&Math.sin(t*10)>0){x.fillStyle=V;x.fillRect(bx-S*.1+w+2,by-S*.058+i*S*.04,2,S*.03)}}}
 else if(m==='wait'){x.beginPath();x.arc(bx,by,S*.085,0,TAU);x.fill();x.stroke();x.strokeStyle=V;x.lineWidth=S*.01;x.beginPath();x.arc(bx,by,S*.095,-Math.PI/2,-Math.PI/2+((t*.5)%1)*TAU);x.stroke();x.fillStyle=V;x.font='bold '+S*(.09+.012*Math.sin(t*4))+'px sans-serif';x.textAlign='center';x.textBaseline='middle';x.fillText('?',bx,by+S*.005)}
 else if(m==='work'){x.strokeStyle='rgba(140,130,180,.35)';x.lineWidth=S*.014;x.beginPath();x.arc(bx,by,S*.065,0,TAU);x.stroke();x.strokeStyle=V;x.beginPath();x.arc(bx,by,S*.065,t*5,t*5+Math.PI*1.2);x.stroke()}
 else if(m==='listen'){x.fillStyle=V;for(let i=0;i<9;i++){const h=S*.014+S*.04*(.5+.5*Math.sin(t*7+i*1.3))*(.4+.6*Math.abs(Math.sin(t*2.1+i))),cx=S/2+(i-4)*S*.045,r=S*.012;x.beginPath();rr(cx-r,S*.955-h/2,2*r,h,r);x.fill()}}
 else if(m==='done'){const p=clamp((1-(this.until-performance.now())/2200)*6,0,1),s=1-Math.pow(1-p,3)+.15*Math.sin(p*Math.PI);x.translate(bx,by);x.scale(s,s);x.fillStyle='#34c759';x.beginPath();x.arc(0,0,S*.075,0,TAU);x.fill();x.strokeStyle='#fff';x.lineWidth=S*.016;x.lineJoin='round';x.beginPath();x.moveTo(-S*.03,0);x.lineTo(-S*.008,S*.025);x.lineTo(S*.035,-S*.025);x.stroke()}
 else if(m==='error'){x.translate(bx+Math.sin(t*30)*S*.004,by);x.fillStyle='#ff453a';x.beginPath();x.arc(0,0,S*.075,0,TAU);x.fill();x.fillStyle='#fff';x.font='bold '+S*.1+'px sans-serif';x.textAlign='center';x.textBaseline='middle';x.fillText('!',0,S*.005)}
 x.restore();
 if(m==='error'){const q=(t*.8)%1,dx=S*.66,dy=S*.3+q*S*.08;x.globalAlpha=1-q*.6;x.fillStyle='#6cc3ff';x.beginPath();x.arc(dx,dy,S*.012,0,TAU);x.moveTo(dx-S*.011,dy-S*.004);x.lineTo(dx,dy-S*.03);x.lineTo(dx+S*.011,dy-S*.004);x.fill();x.globalAlpha=1}}
sky(x,S,t){for(let i=0;i<22;i++){const sx=(Math.sin(i*91.7)*.5+.5)*S,sy=(Math.sin(i*47.3+2)*.5+.5)*S*.8,tw=.5+.5*Math.sin(t*(1+i%4*.6)+i);x.fillStyle='rgba(255,240,200,'+(.25+.6*tw)+')';x.beginPath();x.arc(sx,sy,S*.0035*(1+i%3)*(.6+tw*.6),0,TAU);x.fill()}}
catbits(x,mx,eyy,Rr,a,yaw,rho,fx){x.save();x.lineCap='round';
 x.strokeStyle='rgba(150,64,16,.5)';x.lineWidth=Rr*.2;[-1,0,1].forEach(k=>{const X=fx+yaw*a*.3+k*Rr*.7;x.beginPath();x.moveTo(X,eyy-Rr*3.2+Math.abs(k)*Rr*.3);x.lineTo(X,eyy-Rr*2.1+Math.abs(k)*Rr*.2);x.stroke()});
 x.fillStyle='rgba(255,238,214,.75)';x.beginPath();x.ellipse(mx,eyy+Rr*1.55,Rr,Rr*.7,0,0,TAU);x.fill();
 x.fillStyle='#E8858F';x.beginPath();x.moveTo(mx-Rr*.2,eyy+Rr*1.05);x.lineTo(mx+Rr*.2,eyy+Rr*1.05);x.lineTo(mx,eyy+Rr*1.3);x.closePath();x.fill();
 x.strokeStyle='#8a6a2c';x.lineWidth=Rr*.15;
 [-1,1].forEach(sd=>{const al=sd*.42+yaw,ex=fx+rho*Math.sin(al),ew=Math.cos(al);x.fillStyle='rgba(255,255,255,.1)';x.beginPath();x.ellipse(ex,eyy,Rr*1.3*ew,Rr*1.3,0,0,TAU);x.fill();x.stroke();x.fillStyle='rgba(255,255,255,.4)';x.beginPath();x.ellipse(ex-Rr*.5*ew,eyy-Rr*.85,Rr*.35*ew,Rr*.14,-.5,0,TAU);x.fill()});
 const l=fx+rho*Math.sin(-.42+yaw)+Rr*1.3*Math.cos(-.42+yaw),r=fx+rho*Math.sin(.42+yaw)-Rr*1.3*Math.cos(.42+yaw);x.beginPath();x.moveTo(l,eyy-Rr*.1);x.quadraticCurveTo((l+r)/2,eyy-Rr*.5,r,eyy-Rr*.1);x.stroke();
 x.strokeStyle='rgba(255,246,230,.8)';x.lineWidth=Rr*.07;[-1,1].forEach(sd=>[-.2,.25].forEach(k=>{x.beginPath();x.moveTo(mx+sd*Rr*.9,eyy+Rr*1.5+k*Rr*.4);x.lineTo(mx+sd*Rr*4,eyy+Rr*1.5+k*Rr*1.4+Rr*.2);x.stroke()}));
 x.restore()}
hoodp(x,a,b){for(let i=0;i<=240;i++){const th=i/240*TAU,c=Math.cos(th),sn=Math.sin(th),X=1.13*a*Math.sign(c)*Math.abs(c)**(2/3);let Y=1.1*b*Math.sign(sn)*Math.abs(sn)**(2/3);if(Y<0)Y-=.3*b*Math.exp(-(((X-.12*a)/(.55*a))**2))*Math.min(1,-Y/b);x[i?'lineTo':'moveTo'](X,Y-b)}x.closePath()}
hole(x,a,b){for(let i=0;i<=48;i++){const th=i/48*TAU,c=Math.cos(th),sn=Math.sin(th),X=.86*a*Math.sign(c)*Math.abs(c)**(2/2.6),Y=.8*b*Math.sign(sn)*Math.abs(sn)**(2/2.6);x[i?'lineTo':'moveTo'](X,Y-.98*b)}x.closePath()}
moonstar(x,R,t){x.save();x.shadowColor='#FFE9A8';x.shadowBlur=R*.25;const bob=Math.sin(t*1.8)*R*.04;this.star(x,.53*R,-1.49*R+bob,R*.2*(1+.12*Math.sin(t*3)),Math.sin(t*.6)*.2,'#FFE9A8');this.star(x,.9*R,-1.05*R-bob,R*.08*(1+.25*Math.sin(t*4+1)),0,'#FFF6D6');x.restore()}
star(x,cx,cy,r,o,col){x.save();x.translate(cx,cy);x.rotate(o);x.fillStyle=col;x.beginPath();for(let i=0;i<8;i++){const rr=i%2?r*.32:r,an=i/8*TAU;x[i?'lineTo':'moveTo'](Math.cos(an)*rr,Math.sin(an)*rr)}x.closePath();x.fill();x.restore()}
orbit(x,a,b,t,front){const C=['#FFE9A8','#FFB8D9','#BFD0FF'];for(let i=0;i<3;i++){const an=t*.8+i*TAU/3,sn=Math.sin(an);if((sn>=0)!==front)continue;this.star(x,Math.cos(an)*a*1.5,-b*1.1+sn*b*.45,b*(.14+.05*Math.sin(t*3+i)),t+i,C[i])}}
glow(x,a,b,rgb,t){const g=x.createRadialGradient(0,-b,a*.7,0,-b,a*1.28);g.addColorStop(0,'rgba('+rgb+','+(.35+.08*Math.sin(t*2))+')');g.addColorStop(1,'rgba('+rgb+',0)');x.fillStyle=g;x.beginPath();x.arc(0,-b,a*1.28,0,TAU);x.fill()}
hair(x,a,b,col,low,dir,wv){x.save();this.path(x,a,b);x.clip();x.fillStyle=col;x.beginPath();x.moveTo(-a-5,-2*b-5);x.lineTo(a+5,-2*b-5);for(let i=0;i<=30;i++){const q=i/30;x.lineTo(a-2*a*q,low*b+Math.sin(q*TAU*wv)*.05*b+(q-.5)*dir*b*.5)}x.closePath();x.fill();x.fillStyle='rgba(255,255,255,.18)';x.beginPath();x.ellipse(-a*.3,(low-.28)*b,a*.3,b*.05,-.1,0,TAU);x.fill();x.restore()}
stache(x,mx,y,w,lw,col){x.strokeStyle=col;x.lineWidth=lw;x.lineCap='round';[-1,1].forEach(s=>{x.beginPath();x.moveTo(mx,y);x.quadraticCurveTo(mx+s*w*.55,y+lw*.9,mx+s*w,y-lw*.35);x.stroke()})}
flame(x,cx,base,h,w,col,sw){x.fillStyle=col;x.beginPath();x.moveTo(cx-w,base);x.quadraticCurveTo(cx-w*.9,base-h*.5,cx+sw,base-h);x.quadraticCurveTo(cx+w*.9,base-h*.5,cx+w,base);x.closePath();x.fill()}
face(x,a,b,t){
 const v=this.v,m=this.mood,ink=v.ink,yaw=this.lx*(v.d==='capuz'?.22:.55),rho=a*(v.fs||1),fx=a*(v.fx||0),Rr=Math.max(a*.23,b*.19)*(v.es||1)*(1+.14*this.hv)*(m==='listen'?1.15:1),eyy=-b*v.ey+this.ly*b*.14;
 x.lineCap='round';x.lineJoin='round';
 [-1,1].forEach(sd=>{
  const al=sd*.42+yaw,ex=fx+rho*Math.sin(al),ew=Math.cos(al);
  x.fillStyle='rgba(255,92,120,.3)';x.beginPath();x.ellipse(fx+rho*Math.sin(sd*.8*(v.fs||1)*(v.cs||1)+yaw),eyy+Rr*1.15,Rr*.55*Math.cos(sd*.8+yaw),Rr*.32,0,0,TAU);x.fill();
  x.strokeStyle=ink;x.fillStyle=ink;x.lineWidth=Rr*.3;
  if(m==='happy'||m==='hello'||m==='done'){x.beginPath();x.ellipse(ex,eyy+Rr*.2,Rr*.8*ew,Rr*.7,0,Math.PI*1.1,Math.PI*1.9);x.stroke()}
  else if(m==='sleep'){x.beginPath();x.ellipse(ex,eyy-Rr*.1,Rr*.8*ew,Rr*.5,0,Math.PI*.1,Math.PI*.9);x.stroke()}
  else if(m==='dizzy'){x.lineWidth=Rr*.17;x.beginPath();for(let k=0;k<=40;k++){const r=Rr*.95*k/40,an=k/40*TAU*2.2+t*10*sd;x[k?'lineTo':'moveTo'](ex+r*Math.cos(an)*ew,eyy+r*Math.sin(an))}x.stroke()}
  else{
   const ry=Rr*Math.max(.08,(1-this.bl)*(m==='annoyed'?.72:m==='think'?.85:1)),rx=Rr*.82*ew;
   x.save();if(v.lid&&(m==='idle'||m==='think'||m==='wait'||m==='work')){x.beginPath();x.rect(ex-rx*2,eyy-ry+ry*2*v.lid,rx*4,ry*3);x.clip()}x.beginPath();x.ellipse(ex,eyy+(Rr-ry)*.3,rx,ry,0,0,TAU);x.fill();
   if(this.bl<.4){x.fillStyle='#fff';x.beginPath();x.arc(ex+rx*.3,eyy-ry*(v.lid?-.05:.3),Rr*.26*ew+Rr*.04,0,TAU);x.fill();x.beginPath();x.arc(ex-rx*.3,eyy+ry*.35,Rr*.12,0,TAU);x.fill()}x.restore();
   if(m==='annoyed'||m==='error'){const w=m==='error'?-1:1;x.lineWidth=Rr*.28;x.beginPath();x.moveTo(ex+w*sd*rx*1.25,eyy-ry*1.9);x.lineTo(ex-w*sd*rx*1.2,eyy-ry*.95);x.stroke()}}
 });
 const mx=fx+rho*Math.sin(yaw)*.8,my=eyy+Rr*1.75;if(v.d==='capuz')this.catbits(x,mx,eyy,Rr,a,yaw,rho,fx);x.strokeStyle=ink;x.fillStyle=ink;x.lineWidth=Rr*.22;
 if(m==='speak'){x.beginPath();x.ellipse(mx,my+Rr*.05,Rr*.4,Rr*(.12+.4*Math.abs(Math.sin(t*9))),0,0,TAU);x.fill()}
 else if(m==='think'||m==='wait'||m==='work'){const o=m==='think'?Rr*.25:0;x.beginPath();x.moveTo(mx-Rr*.3+o,my);x.lineTo(mx+Rr*.3+o,my-(o?Rr*.12:0));x.stroke()}
 else if(m==='listen'){x.beginPath();x.ellipse(mx,my,Rr*.14,Rr*.18,0,0,TAU);x.fill()}
 else if(m==='error'){x.beginPath();x.moveTo(mx-Rr*.5,my);for(let k=1;k<=4;k++)x.lineTo(mx-Rr*.5+k*Rr*.25,my+(k%2?-1:1)*Rr*.1);x.stroke()}
 else if(m==='hello'||m==='happy'||m==='dance'||m==='done'){x.beginPath();x.moveTo(mx-Rr*.55,my-Rr*.1);x.quadraticCurveTo(mx,my+Rr*1.1,mx+Rr*.55,my-Rr*.1);x.closePath();x.fill();x.fillStyle='#ff7b8f';x.beginPath();x.ellipse(mx,my+Rr*.42,Rr*.28,Rr*.16,0,0,TAU);x.fill()}
 else if(m==='annoyed'){x.beginPath();x.moveTo(mx-Rr*.45,my+Rr*.08);x.quadraticCurveTo(mx,my-Rr*.1,mx+Rr*.45,my+Rr*.08);x.stroke()}
 else if(m==='dizzy'){x.beginPath();x.ellipse(mx,my,Rr*.2,Rr*.26*(1+.25*Math.sin(t*6)),0,0,TAU);x.fill()}
 else if(m==='sleep'){const q=.12+.1*(.5+.5*Math.sin(t*1.2));x.beginPath();x.ellipse(mx,my,Rr*q*2,Rr*q*2.4,0,0,TAU);x.fill()}
 else{x.beginPath();x.arc(mx,my-Rr*.2,Rr*.45,Math.PI*.15,Math.PI*.85);x.stroke()}
}
}


const IDS = ['pudim','nuvem','mint','orange','blue','cacto','purple','queijinho',
  'algodao','lua','tesla','einstein','turing','ada','grace','curie','oxta'];
export const DOT_COMPANIONS = V.map((variant,i) => ({ id: IDS[i], label: variant.n }));
export function companionIdFor(identity) {
  let hash=0;
  for(const ch of String(identity||''))hash=(hash*31+ch.charCodeAt(0))>>>0;
  return IDS[hash%IDS.length];
}
const TYPES=new Map(IDS.map((id,i)=>[id,V[i]]));

export function createCompanion(canvas, id, mood='idle') {
  const variant=TYPES.get(id)||TYPES.get('blue');
  const mini=new Mini(variant,canvas);
  mini.baseMood='idle';
  let visible=true, raf=0, timer=0, last=0, destroyed=false;
  let reduced=window.matchMedia?.('(prefers-reduced-motion: reduce)').matches===true;
  const motionQuery=window.matchMedia?.('(prefers-reduced-motion: reduce)');
  function frame(now){
    raf=0;
    if(destroyed||!visible||document.hidden)return;
    const rate=mini.S<=48?100:mini.S<=90?50:33;
    const dt=last?Math.min(.05,(now-last)/1000):.016;
    last=now;mini.step(dt,now/1000,now);mini.draw(now/1000);
    if(!reduced)timer=window.setTimeout(()=>{timer=0;raf=requestAnimationFrame(frame);},rate);
  }
  function render(){
    if(destroyed)return;
    if(raf)cancelAnimationFrame(raf);
    if(timer)clearTimeout(timer);
    raf=0;timer=0;last=0;
    if(visible&&!document.hidden){
      if(reduced){mini.draw(performance.now()/1000);}
      else raf=requestAnimationFrame(frame);
    }
  }
  function visibilityChanged(){render();}
  function reduceChanged(e){reduced=e.matches;render();}
  const intersection=typeof IntersectionObserver==='function'
    ? new IntersectionObserver(entries=>{visible=entries[0]?.isIntersecting??false;render();})
    : null;
  if(intersection)intersection.observe(canvas);
  document.addEventListener('visibilitychange',visibilityChanged);
  motionQuery?.addEventListener?.('change',reduceChanged);
  listenPointer();
  function update(state){
    const next=['idle','listen','think','work','speak','wait','done','error','sleep'].includes(state)?state:'idle';
    if(mini.baseMood!==next){
      mini.baseMood=next==='done'?'idle':next;
      mini.set(next,next==='idle'?0:next==='done'?2200:Infinity);
      render();
    }
  }
  update(mood);
  render();
  return {
    update,
    destroy(){
      destroyed=true;
      if(raf)cancelAnimationFrame(raf);
      if(timer)clearTimeout(timer);
      intersection?.disconnect();
      mini.observer.disconnect();
      document.removeEventListener('visibilitychange',visibilityChanged);
      motionQuery?.removeEventListener?.('change',reduceChanged);
      unlistenPointer();
    }
  };
}
