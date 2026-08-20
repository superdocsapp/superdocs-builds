import "dotenv/config";
import { createApp } from "./app.js";

const PORT = process.env.PORT || 3000;

createApp().listen(PORT, () => {
  console.log(`Resume Tailor running at http://localhost:${PORT}`);
});