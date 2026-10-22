// SENTRA DOM adapter for the MIT Coucou ticker. No state, authority or HTML strings.
export function h(tag: string, attrs: Record<string, unknown> = {}, ...children: any[]) {
 const el = document.createElement(tag);
 for (const [key,value] of Object.entries(attrs)) {
  if (key === 'class') el.className = String(value);
  else if (key === 'text') el.textContent = String(value);
  else if (key === 'style') for (const declaration of String(value).split(';')) { const colon = declaration.indexOf(':'); if(colon > 0) el.style.setProperty(declaration.slice(0,colon).trim(),declaration.slice(colon+1).trim()); }
  else el.setAttribute(key, String(value));
 }
 for (const child of children.flat()) if (child != null && child !== false) el.append(typeof child === 'string' ? document.createTextNode(child) : child);
 return el;
}
export function svg(path: string, size = 14, opts: { fill?: string; stroke?: number; evenOdd?: boolean } = {}) {
 const el = document.createElementNS('http://www.w3.org/2000/svg','svg');
 el.setAttribute('viewBox','0 0 24 24');el.setAttribute('width',String(size));el.setAttribute('height',String(size));el.setAttribute('aria-hidden','true');
 const p = document.createElementNS('http://www.w3.org/2000/svg','path');p.setAttribute('d',path);
 p.setAttribute('fill',opts.stroke ? 'none' : opts.fill ?? 'currentColor');
 if(opts.stroke){p.setAttribute('stroke','currentColor');p.setAttribute('stroke-width',String(opts.stroke));p.setAttribute('stroke-linecap','round');p.setAttribute('stroke-linejoin','round');}
 if(opts.evenOdd)p.setAttribute('fill-rule','evenodd');el.append(p);return el;
}
