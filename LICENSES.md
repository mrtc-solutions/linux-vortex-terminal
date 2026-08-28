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

## Third-party software

VORTEX does not vendor third-party agent or scanner source. Adapters only probe
for a local executable. See [`NOTICE`](NOTICE) for agent attribution.

The optional Electron desktop shell is MIT-licensed (devDependency).

The Android APK client is part of VORTEX and is MIT-licensed. It is a WebView
of the same workbench API; it does not embed Kali tools on the phone.

Host tools discovered on PATH keep their own upstream licenses (GPL, Apache-2.0,
MIT, NPSL, and others). VORTEX records the catalog license hint and does not
relicense those binaries.
