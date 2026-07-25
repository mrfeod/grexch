import assert from "node:assert/strict";
import test from "node:test";

import { htmlToText } from "../src/index.js";

test("converts the result table into readable text", () => {
  const html = `
    <html><body>
      <h4>Αποτελέσματα</h4>
      <table><tr><th>Επίπεδο</th><td>Β1</td></tr>
      <tr><th>Επιτυχία</th><td><img src="/certification/img/checkon.png"></td></tr></table>
    </body></html>
  `;

  assert.equal(htmlToText(html), "Αποτελέσματα\nΕπίπεδο Β1\nΕπιτυχία ✓");
});

test("removes scripts, images and decodes entities", () => {
  const html =
    "<style>x</style><p>A&nbsp;&amp;&#x2713;</p><script>bad</script><img src='x.png'>";

  assert.equal(htmlToText(html), "A &✓");
});
