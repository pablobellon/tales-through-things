// Live reload while developing: when tools/serve.py sees a saved file, reload the page.
// Does nothing when the page is served by something else (no /__version endpoint).
let known = null;

async function check() {
  try {
    const res = await fetch('/__version', { cache: 'no-store' });
    if (!res.ok) return; // not our server: stop polling
    const v = await res.text();
    if (known === null) known = v;
    else if (v !== known) return location.reload();
  } catch {
    // server restarting or offline: try again later
  }
  setTimeout(check, 1000);
}
check();
