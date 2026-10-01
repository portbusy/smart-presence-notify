const fs = require('fs');
const path = require('path');
const sharp = require('sharp');
const dir = __dirname;
const ink = '#282B44', blue = '#5552EB', mint = '#75E4B2', green = '#14805F';
const mark = (ring, dot) => `<path d="M126 49H101C67 49 49 67 49 101V155C49 189 67 207 101 207H155C189 207 207 189 207 155V130" fill="none" stroke="${ring}" stroke-width="34" stroke-linecap="round"/><circle cx="187" cy="69" r="28" fill="${dot}"/>`;
const svg = (w,h,body) => `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">${body}</svg>`;
const text = (x,y,size,weight,fill,content,extra='') => `<text x="${x}" y="${y}" font-family="Avenir Next, Avenir, sans-serif" font-size="${size}" font-weight="${weight}" fill="${fill}" ${extra}>${content}</text>`;
const wordmark = (dark) => `<g transform="translate(12 12) scale(.68)">${mark(dark ? '#DBDAFF' : blue,dark ? mint : green)}</g>${text(210,88,38,600,dark?'#F8F8FF':ink,'Smart Presence')}${text(210,142,48,700,dark?mint:blue,'Notify')}`;
const write = (name,w,h,body) => fs.writeFileSync(path.join(dir,name+'.svg'),svg(w,h,body));
write('icon',256,256,mark(blue,green));
write('icon_dark',256,256,mark('#DBDAFF',mint));
write('app_icon',256,256,`<rect width="256" height="256" rx="58" fill="${blue}"/>`+`<g transform="translate(14 14) scale(.89)">${mark('#FFFFFF',mint)}</g>`);
write('logo',640,200,wordmark(false));
write('logo_dark',640,200,wordmark(true));
const b = [];
b.push(`<rect width="1440" height="1060" fill="#F6F5F0"/>`);
b.push(text(68,70,16,600,'#727484','SMART PRESENCE NOTIFY / BRAND EXPLORATION', 'letter-spacing="2"'));
b.push(text(68,133,52,700,ink,'Il segnale trova casa.'));
b.push(text(70,175,21,400,'#6B6E7D','Un varco aperto. Una presenza che arriva. La notifica al momento giusto.'));
b.push(`<rect x="68" y="220" width="638" height="420" rx="28" fill="#FFFFFF"/><rect x="734" y="220" width="638" height="420" rx="28" fill="${ink}"/>`);
b.push(text(102,265,13,600,'#9092A0','01 / LIGHT','letter-spacing="2"'));
b.push(text(768,265,13,600,'#A6A8B8','02 / DARK','letter-spacing="2"'));
b.push(`<g transform="translate(259 285) scale(.92)">${mark(blue,green)}</g><g transform="translate(925 285) scale(.92)">${mark('#DBDAFF',mint)}</g>`);
b.push(`<g transform="translate(123 487) scale(.84)">${wordmark(false)}</g><g transform="translate(789 487) scale(.84)">${wordmark(true)}</g>`);
b.push(`<rect x="68" y="668" width="396" height="294" rx="28" fill="#E9E8FC"/>`);
b.push(text(102,713,13,600,'#747199','03 / APP ICON','letter-spacing="2"'));
b.push(`<g transform="translate(182 749) scale(.65)"><rect width="256" height="256" rx="58" fill="${blue}"/><g transform="translate(14 14) scale(.89)">${mark('#FFFFFF',mint)}</g></g>`);
b.push(`<rect x="492" y="668" width="456" height="294" rx="28" fill="#FFFFFF"/>`);
b.push(text(526,713,13,600,'#9092A0','04 / PICCOLE DIMENSIONI','letter-spacing="2"'));
for (const [x,y,s] of [[532,790,16],[590,785,24],[663,780,32],[750,764,48],[842,748,64]]) {
 b.push(`<g transform="translate(${x} ${y}) scale(${s/256})">${mark(blue,green)}</g>`);
 b.push(text(x+s/2,y+s+37,13,500,'#6B6E7D',s+' px','text-anchor="middle"'));
}
b.push(text(526,924,15,400,'#747784','Una sola forma. Nessun dettaglio da decifrare.'));
b.push(`<rect x="976" y="668" width="396" height="294" rx="28" fill="#FFFFFF"/>`);
b.push(text(1010,713,13,600,'#9092A0','05 / PALETTE','letter-spacing="2"'));
for(const [x,c,label,hex] of [[1010,blue,'Signal','#5552EB'],[1120,mint,'Presence','#75E4B2'],[1230,ink,'Midnight','#282B44']]){
 b.push(`<rect x="${x}" y="755" width="86" height="92" rx="16" fill="${c}"/>`);
 b.push(text(x,879,13,600,ink,label)); b.push(text(x,902,12,400,'#747784',hex));
}
b.push(text(68,1016,15,500,'#777987','DIREZIONE 01 — VARCO', 'letter-spacing="1.5"'));
b.push(text(1372,1016,15,400,'#777987','Concept originale · SVG vettoriali · PNG trasparenti','text-anchor="end"'));
write('presentation',1440,1060,b.join(''));
(async()=>{
 for (const name of fs.readdirSync(dir).filter(x=>x.endsWith('.svg'))) await sharp(path.join(dir,name)).png().toFile(path.join(dir,name.replace('.svg','.png')));
 for (const s of [16,24,32,48,64]) await sharp(path.join(dir,'icon.svg')).resize(s,s).png().toFile(path.join(dir,`icon_${s}.png`));
})().catch(e=>{console.error(e); process.exitCode=1});
