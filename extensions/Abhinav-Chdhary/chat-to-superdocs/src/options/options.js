const input = document.querySelector("#bridge-url");
const status = document.querySelector("#status");

chrome.storage.local.get({ bridgeUrl: "http://127.0.0.1:8787" }).then(({ bridgeUrl }) => { input.value = bridgeUrl; });
document.querySelector("#save").addEventListener("click", async () => {
  try {
    const url = new URL(input.value);
    if (url.origin !== "http://127.0.0.1:8787") throw new Error("This first draft supports the local bridge at http://127.0.0.1:8787 only.");
    await chrome.storage.local.set({ bridgeUrl: url.toString().replace(/\/$/, "") });
    status.textContent = "Saved.";
  } catch (error) { status.textContent = error.message; }
});
