# Direzione 01 — Varco

**Il segnale trova casa.**

Un perimetro morbido e aperto rappresenta lo spazio domestico; il punto entra nel varco e rappresenta una presenza, oppure una notifica che raggiunge la sua destinazione. Il segno mantiene un'unica silhouette riconoscibile senza sommare casa, omino e campanella.

Viola elettrico per il segnale, verde per la presenza, blu notte per gli sfondi. Il punto usa un verde più scuro su bianco per mantenere contrasto; nella variante scura e nell'icona app usa menta. La tipografia è Avenir Next, con fallback Avenir e sans-serif.

## Asset

- `icon.svg` / `icon.png`: icona trasparente 256 × 256 per sfondi chiari.
- `icon_dark.svg` / `icon_dark.png`: icona trasparente 256 × 256 per sfondi scuri.
- `app_icon.svg` / `app_icon.png`: variante con contenitore viola arrotondato.
- `logo.svg` / `logo.png`: logo trasparente 640 × 200 per sfondi chiari.
- `logo_dark.svg` / `logo_dark.png`: logo trasparente 640 × 200 per sfondi scuri.
- `icon_16.png`, `icon_24.png`, `icon_32.png`, `icon_48.png`, `icon_64.png`: riduzioni per verifica di leggibilità.
- `presentation.svg` / `presentation.png`: tavola di presentazione 1440 × 1060.
- `create.cjs`: sorgente per rigenerare tutti gli asset con Node.js e sharp disponibili.

Gli SVG dell'icona sono indipendenti dai font. I logo SVG mantengono testo editabile: i PNG consegnati fissano la resa tipografica visualizzata sulla tavola. La proposta è stata approvata. Gli asset distribuiti, rifilati e adattati alle specifiche Home Assistant, si trovano in `custom_components/smart_presence_notify/brand/`. Questa cartella conserva la tavola e i materiali di esplorazione.

Verifica visiva completata sulla tavola renderizzata: chiaro/scuro, logo coordinato, variante app e riduzioni 16–64 px. Per l'uso nelle liste Home Assistant sono preferibili i file trasparenti.
