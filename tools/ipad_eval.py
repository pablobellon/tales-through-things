"""Run JavaScript inside the sequence pages open on a USB-connected iPad.

usage: ~/Library/Python/3.9/bin/python3 tools/ipad_eval.py "<js expression>"   (or no argument = measure)
needs: pip install --user pymobiledevice3 ; on the iPad: Settings → Apps → Safari →
       Advanced → Web Inspector ON, and the page open (Safari tab or Home Screen app).
"""
import asyncio
import json
import sys
import warnings

warnings.filterwarnings('ignore')

from pymobiledevice3.lockdown import create_using_usbmux  # noqa: E402
from pymobiledevice3.services.webinspector import WebinspectorService  # noqa: E402

MEASURE = r"""
(() => {
  const probe = document.createElement('div');
  probe.style.cssText = 'position:fixed;top:0;left:0;padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left)';
  document.body.appendChild(probe);
  const cs = getComputedStyle(probe);
  const safe = { top: cs.paddingTop, right: cs.paddingRight, bottom: cs.paddingBottom, left: cs.paddingLeft };
  probe.remove();
  const r = (el) => { if (!el) return null; const b = el.getBoundingClientRect(); return [Math.round(b.left), Math.round(b.top), Math.round(b.width), Math.round(b.height)]; };
  return JSON.stringify({
    url: location.href,
    standalone: navigator.standalone === true || matchMedia('(display-mode: standalone)').matches,
    visible: document.visibilityState,
    screen: [screen.width, screen.height],
    inner: [innerWidth, innerHeight],
    client: [document.documentElement.clientWidth, document.documentElement.clientHeight],
    visualViewport: visualViewport ? [Math.round(visualViewport.width), Math.round(visualViewport.height), Math.round(visualViewport.offsetTop)] : null,
    dpr: devicePixelRatio,
    safeArea: safe,
    bg: r(document.getElementById('bg')),
    disc: r(document.getElementById('disc')),
    rootBg: getComputedStyle(document.documentElement).backgroundColor,
    bodyBg: getComputedStyle(document.body).backgroundColor,
    hud: (document.getElementById('hud') || {}).textContent,
  });
})()
"""


async def evaluate(inspector, ap, expr):
    session = await inspector.inspector_session(ap.application, ap.page)
    await session.runtime_enable()
    return await session.runtime_evaluate(expr, return_by_value=True)


async def main(expr):
    lockdown = await create_using_usbmux()
    inspector = WebinspectorService(lockdown=lockdown)
    await inspector.connect()
    try:
        pages = await inspector.get_open_application_pages(timeout=1.5)
        found = False
        for ap in pages:
            url = getattr(ap.page, 'web_url', '') or ''
            if ':8443' not in url:
                continue
            found = True
            print(f'--- {ap.application.name} · {url}', flush=True)
            try:
                result = await asyncio.wait_for(evaluate(inspector, ap, expr), 8)
            except asyncio.TimeoutError:
                print('   (no answer: background tab or app not in front)')
                continue
            try:
                print(json.dumps(json.loads(result), indent=2))
            except (TypeError, ValueError):
                print(result)
        if not found:
            print('No page of the site found. Open it on the iPad. Pages seen:')
            for ap in pages:
                print('  ', ap.application.name, getattr(ap.page, 'web_url', ''))
    finally:
        await inspector.close()


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else MEASURE))
