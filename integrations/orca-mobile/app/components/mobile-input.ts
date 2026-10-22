const codes:Record<string,number>={q:16,w:17,e:18,r:19,t:20,y:21,u:22,i:23,o:24,p:25,a:30,s:31,d:32,f:33,g:34,h:35,j:36,k:37,l:38,z:44,x:45,c:46,v:47,b:48,n:49,m:50,' ':57,'\n':28,'\t':15};
for(const [characters,start] of [['1234567890',2],['-=',12],['[]',26],[";'",39],['`',41],['\\',43],[',./',51]] as const)[...characters].forEach((c,i)=>codes[c]=start+i);
const shifted='!@#$%^&*()_+{}:"~|<>?',plain='1234567890-=[];\'`\\,./';
/** Physical US key positions; the guest keyboard layout controls the characters. */
export function textChords(text:string):number[][][]{
 if([...text].length>128)throw Error('Envie no máximo 128 caracteres por vez.');
 return [...text].map(character=>{const lower=character.toLowerCase(),shift=shifted.indexOf(character);const code=codes[shift>=0?plain[shift]:lower];if(!code)throw Error('Caractere sem tecla física mapeada. Use o terminal para texto Unicode.');return character!==lower||shift>=0?[[42],[code]]:[[code]]});
}
export function framebufferPoint(x:number,y:number,width:number,height:number,sourceWidth:number,sourceHeight:number):number[]{
 return [Math.max(1,Math.min(sourceWidth,Math.round(x/Math.max(1,width)*sourceWidth))),Math.max(1,Math.min(sourceHeight,Math.round(y/Math.max(1,height)*sourceHeight)))];
}
