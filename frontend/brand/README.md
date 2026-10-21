# Brand images

Sources of the images in `public/`, which are these drawings rendered to PNG/JPEG (in a browser:
draw the SVG on a canvas of the size below, then save it with `canvas.toBlob`).

| File in `public/`        | Source                         | Size     | Used for                                   |
| ------------------------ | ------------------------------ | -------- | ------------------------------------------ |
| `favicon.svg`            | itself                         | any      | browser tab                                |
| `favicon.ico`            | `public/favicon.svg`           | 32×32    | browsers that ask for `/favicon.ico`       |
| `icon-192.png`           | `public/favicon.svg`           | 192×192  | installed app (manifest, "any")            |
| `icon-512.png`           | `public/favicon.svg`           | 512×512  | installed app, splash screen               |
| `icon-maskable-512.png`  | `icon-full.svg`                | 512×512  | Android icon shapes (manifest, "maskable") |
| `apple-touch-icon.png`   | `icon-full.svg`                | 180×180  | iPhone/iPad home screen                    |
| `og-image.jpg`           | `og-image.svg`                 | 1200×630 | link previews (JPEG, quality 0.9)          |

`favicon.ico` holds the 32×32 PNG as its only image.
