// Records the "two buyers race for the last unit of stock" demo:
// two independent browser sessions (separate users, separate carts) both
// click Checkout on a stock=1 product at the same moment. Exactly one
// should succeed; the other should see a rejection, in real time.
import { chromium } from "playwright";
import fs from "node:fs";

const FRONTEND = "http://localhost:5173";
const PRODUCT_NAME = "Ember Ceramic Mug Set";
const VIDEO_DIR = "race_videos";

fs.rmSync(VIDEO_DIR, { recursive: true, force: true });
fs.mkdirSync(VIDEO_DIR, { recursive: true });

const browser = await chromium.launch();

async function newBuyer(label) {
  const context = await browser.newContext({
    viewport: { width: 640, height: 720 },
    recordVideo: { dir: `${VIDEO_DIR}/${label}`, size: { width: 640, height: 720 } },
  });
  const page = await context.newPage();
  const email = `${label}-${Date.now()}@race-demo.test`;
  await page.goto(`${FRONTEND}/login`, { waitUntil: "networkidle" });
  await page.fill("#email", email);
  await page.fill("#password", "RaceDemo123!");
  await page.click("text=Create an account");
  await page.waitForURL(`${FRONTEND}/`, { timeout: 15000 });
  return { context, page, label };
}

console.log("Signing up two independent buyers...");
const [buyerA, buyerB] = await Promise.all([newBuyer("buyer-a"), newBuyer("buyer-b")]);

for (const buyer of [buyerA, buyerB]) {
  await buyer.page.waitForSelector(`text=${PRODUCT_NAME}`, { timeout: 15000 });
  const card = buyer.page.locator(".product-card", { hasText: PRODUCT_NAME });
  await card.locator("button", { hasText: "Add to cart" }).click();
  await buyer.page.waitForTimeout(300);
  await buyer.page.goto(`${FRONTEND}/cart`, { waitUntil: "networkidle" });
  console.log(`${buyer.label} ready at cart, has item in cart.`);
}

// A short recorded beat before the race so the GIF has visible "before" state.
await new Promise((r) => setTimeout(r, 1000));

console.log("Racing checkout for both buyers at the same instant...");
const results = await Promise.allSettled([
  buyerA.page.click("button:has-text('Checkout')"),
  buyerB.page.click("button:has-text('Checkout')"),
]);
console.log("Click results:", results.map((r) => r.status));

// Let both UIs settle (success -> redirect toward Stripe, failure -> inline error).
// The winning checkout makes a real Stripe API call (~4s), so give enough
// headroom for window.location.href to actually fire before we inspect it.
await Promise.all([
  buyerA.page.waitForTimeout(9000),
  buyerB.page.waitForTimeout(9000),
]);

for (const buyer of [buyerA, buyerB]) {
  const url = buyer.page.url();
  const errorText = await buyer.page.locator(".error").first().textContent().catch(() => null);
  console.log(`${buyer.label}: url=${url} error=${errorText}`);
}

await buyerA.context.close();
await buyerB.context.close();
await browser.close();
console.log("Done. Videos in", VIDEO_DIR);
