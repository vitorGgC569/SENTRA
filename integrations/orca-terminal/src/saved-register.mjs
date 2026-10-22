// Audited boundary for the pinned headless .303 / renderer .304 buffer registers.
const integer=value=>Number.isSafeInteger(value)&&value>=0&&value<=0xffffffff;
function charsets(value){
 if(!Array.isArray(value)||value.length>4)throw Error('Invalid terminal charset register');
 return value.map(table=>{
  if(table==null)return null;
  const entries=Object.entries(table);
  if(entries.length>128||entries.some(([key,v])=>key.length!==1||typeof v!=='string'||v.length>8))throw Error('Invalid terminal charset table');
  return Object.fromEntries(entries);
 });
}
export function captureSavedRegister(terminal,buffer=terminal._core?.buffer){
 const attributes=buffer?.savedCurAttrData;
 if(!attributes||!integer(attributes.fg)||!integer(attributes.bg))throw Error('Pinned terminal saved attributes unavailable');
 const urlId=attributes.extended?.urlId||0;
 const uri=urlId?terminal._core?._oscLinkService?.getLinkData(urlId)?.uri:null;
 return {x:buffer.savedX,y:buffer.savedY-buffer.ybase,fg:attributes.fg,bg:attributes.bg,
  extended:attributes.extended?._ext||0,uri:uri||null,charsets:charsets(buffer.savedCharsets||[]),
  glevel:buffer.savedGlevel||0,origin:buffer.savedOriginMode===true,wrap:buffer.savedWraparoundMode!==false};
}
export function restoreSavedRegister(terminal,register,buffer=terminal._core?.buffer){
 if(!register)return;
 if(!integer(register.fg)||!integer(register.bg)||!integer(register.extended)||
  !Number.isSafeInteger(register.x)||register.x<0||register.x>500||
  !Number.isSafeInteger(register.y)||Math.abs(register.y)>50000||
  !Number.isInteger(register.glevel)||register.glevel<0||register.glevel>3||
  register.uri!==null&&(typeof register.uri!=='string'||register.uri.length>8192))throw Error('Invalid saved terminal register');
 if(!buffer?.savedCurAttrData)throw Error('Pinned terminal register API unavailable');
 buffer.savedX=register.x;buffer.savedY=Math.max(0,buffer.ybase+register.y);
 buffer.savedOriginMode=register.origin===true;buffer.savedWraparoundMode=register.wrap===true;
 buffer.savedCharsets=charsets(register.charsets);buffer.savedGlevel=register.glevel;
 buffer.savedCharset=buffer.savedCharsets[register.glevel]||undefined;
 buffer.savedCurAttrData.fg=register.fg;buffer.savedCurAttrData.bg=register.bg;
 buffer.savedCurAttrData.extended._ext=register.extended;
 buffer.savedCurAttrData.extended._urlId=register.uri?terminal._core._oscLinkService.registerLink({uri:register.uri}):0;
}

export function captureSavedRegisters(terminal){
 const buffers=terminal._core?.buffers;
 return {version:1,normal:captureSavedRegister(terminal,buffers?.normal),
  alternate:captureSavedRegister(terminal,buffers?.alt)};
}
export function restoreSavedRegisters(terminal,registers){
 if(!registers)return;
 if(registers.version!==1)throw Error('Unsupported saved terminal registers');
 const buffers=terminal._core?.buffers;
 restoreSavedRegister(terminal,registers.normal,buffers?.normal);
 restoreSavedRegister(terminal,registers.alternate,buffers?.alt);
}
