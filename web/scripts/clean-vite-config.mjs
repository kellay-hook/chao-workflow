import { existsSync, unlinkSync } from 'node:fs'

for (const file of ['vite.config.js', 'vite.config.d.ts']) {
  if (existsSync(file)) unlinkSync(file)
}
