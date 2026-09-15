/* Minimal libGL.so.1 for headless acceptance containers (see README.md).
   Qt's GUI library declares libGL.so.1 as DT_NEEDED even though the VNC platform
   plugin paints with the raster engine only. These four entry points are the only
   GL symbols libQt5Gui references; each aborts if it is ever called, so a GL code
   path cannot be silently faked. */
#include <stdio.h>
#include <stdlib.h>

static void unreachable(const char *fn) {
    fprintf(stderr, "gl-shim: %s was called; the raster path was expected\n", fn);
    abort();
}

void glLoadIdentity(void) { unreachable("glLoadIdentity"); }
void glLoadMatrixf(const float *matrix) { (void)matrix; unreachable("glLoadMatrixf"); }
void glMatrixMode(unsigned int mode) { (void)mode; unreachable("glMatrixMode"); }
void glOrtho(double left, double right, double bottom, double top, double near, double far) {
    (void)left; (void)right; (void)bottom; (void)top; (void)near; (void)far;
    unreachable("glOrtho");
}
