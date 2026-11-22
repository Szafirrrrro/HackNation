const assert = require("node:assert/strict");
const { chromium } = require("./.venv/Lib/site-packages/playwright/driver/package");

async function open(browser, width, height) {
    const page = await browser.newPage({viewport: {width, height}});
    page.setDefaultTimeout(15000);
    await page.goto("http://127.0.0.1:8582/");
    await page.getByRole("heading", {name: "Mapa kampanii", exact: true}).waitFor();
    const demo = page.getByRole("radio", {name: "Demo syntetyczne", exact: true});
    if (!(await demo.isChecked())) await page.getByText("Demo syntetyczne", {exact: true}).first().click();
    const frame = page.frameLocator(".st-key-analyst-graph iframe");
    await frame.locator("#node-picker").waitFor();
    return [page, frame];
}

async function clickLine(frame, title) {
    const canvas = frame.locator("canvas");
    const position = await canvas.evaluate((canvas, title) => {
        network.stopSimulation();
        for (let y = 70; y < canvas.clientHeight - 5; y += 3) {
            for (let x = 8; x < canvas.clientWidth - 8; x += 3) {
                const point = {x, y};
                const edge = edges.get(network.getEdgeAt(point) ?? "");
                if (edge?.detailTitle === title && network.getNodeAt(point) === undefined) return point;
            }
        }
        return null;
    }, title);
    assert(position, `Could not find a clickable line for ${title}`);
    await canvas.click({position});
    assert.equal(await frame.locator("#node-title").textContent(), title);
    assert.equal(await frame.locator("#edge-endpoints li").count(), 2);
}

async function main() {
    const browser = await chromium.launch({channel: "chrome"});
    try {
        const [page, frame] = await open(browser, 1440, 1000);
        const picker = frame.locator("#node-picker");
        const edgePicker = frame.locator("#edge-picker");
        const appStyles = await page.locator(".stApp").evaluate(el =>
            getComputedStyle(el).backgroundImage);
        assert.match(appStyles, /rgb\(27, 27, 27\).*rgb\(17, 17, 17\)/);
        assert.equal(await frame.locator("body").evaluate(el => getComputedStyle(el).backgroundColor),
                     "rgb(21, 21, 21)");
        const node = await frame.locator("canvas").evaluate(() => nodes.get("A00"));
        assert.notEqual(node.label, node.id);
        assert(node.label.length <= 26);
        await picker.selectOption("A00");
        assert.equal(await frame.locator("#node-title").textContent(), node.detailTitle);
        assert.match(await frame.locator("#node-details").textContent(), /A00/);
        await edgePicker.selectOption({index: 1});
        assert.equal(await frame.locator("#edge-endpoints li").count(), 2);
        await edgePicker.press("Escape");
        assert(await frame.locator("article").isHidden());
        await frame.locator("canvas").evaluate(() => new Promise(resolve => setTimeout(resolve, 1300)));
        await page.screenshot({path: ".analyst-labels-preview.png"});
        await clickLine(frame, "Podobieństwo materiałów");
        assert.match(await frame.locator("#node-details").textContent(), /Podobieństwo.+Ocena kampanii/);
        assert(await frame.locator("#edge-reasons li").count() > 0);
        await page.screenshot({path: ".analyst-edge-preview.png"});
        await frame.locator("#node-close").click();
        await clickLine(frame, "Członek kampanii");
        assert.match(await frame.locator("#node-details").textContent(), /zbiorze odniesienia/);
        await page.locator(".analyst-nav a[href='#os-czasu']").click();
        const timeline = page.locator(".st-key-analyst-timeline");
        await timeline.getByText("Data publikacji nieustalona: 27", {exact: true}).waitFor();
        console.log("Desktop graph labels, keyboard selection, similarity and membership line clicks, date count and neutral colors passed.");

        const [mobile, mobileFrame] = await open(browser, 390, 844);
        const mobilePicker = mobileFrame.locator("#node-picker");
        const mobileEdgePicker = mobileFrame.locator("#edge-picker");
        await mobilePicker.selectOption("A00");
        await mobileEdgePicker.selectOption({index: 1});
        await mobileFrame.locator("#edge-endpoints").waitFor();
        const bounds = await mobileFrame.locator("article").evaluate(el => {
            const rect = el.getBoundingClientRect();
            return [rect.left, rect.right, window.innerWidth];
        });
        assert(bounds[0] >= 0 && bounds[1] <= bounds[2] + 1);
        assert(await mobile.getByTestId("stMain").evaluate(el => el.scrollWidth <= el.clientWidth));
        console.log("Mobile connection card opens and fits.");
    } finally {
        await browser.close();
    }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
