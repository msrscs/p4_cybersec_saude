import { createApp } from './app.js';

const port = Number.parseInt(process.env.PORT ?? '3000', 10);
const host = process.env.HOST ?? '127.0.0.1';
const apiUrl = process.env.API_URL ?? 'http://127.0.0.1:8000';

createApp({ apiUrl }).listen(port, host, () => {
  console.log(`Frontend ouvindo em http://${host}:${port}`);
});
