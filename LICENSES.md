# Licenses

VORTEX is free and open-source software.

## SPDX identifier

**MIT**

The full text is in [`LICENSE`](LICENSE).

Copyright (c) 2026 mrtc-solutions

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## noVNC (bundled RFB client) — MPL-2.0

The authorized remote-desktop window renders the live framebuffer with
[noVNC](https://github.com/novnc/noVNC), bundled as the npm package
`@novnc/novnc` and inlined into the single-file production document
(`dist/index.html`) by the Vite build. It is not fetched at runtime and no
third-party script is executed from the network.

noVNC is licensed under the Mozilla Public License 2.0 (MPL-2.0). The full
license text ships with the npm package at
`node_modules/@novnc/novnc/LICENSE.txt`. Vortex Terminal does not modify noVNC:
source and license are unchanged, so MPL-2.0's file-level copyleft imposes no
obligation on Vortex Terminal's own MIT-licensed code.

The RFB server itself is *not* bundled: Vortex speaks RFB to an endpoint the
operator is already authorized to reach.

## Third-party software

VORTEX does not vendor third-party agent or scanner source. Adapters only probe
for a local executable. See [`NOTICE`](NOTICE) for agent attribution.

The optional Electron desktop shell is MIT-licensed (devDependency).

The Android APK client is part of VORTEX and is MIT-licensed. It is a WebView
of the same workbench API; it does not embed Kali tools on the phone.

Host tools discovered on PATH keep their own upstream licenses (GPL, Apache-2.0,
MIT, NPSL, and others). VORTEX records the catalog license hint and does not
relicense those binaries.
