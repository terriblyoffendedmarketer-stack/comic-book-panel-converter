/* dither_native.c — C implementations of error-diffusion dithering
 * Compiled at runtime by xtc_pipeline.py via ctypes.
 * Build: cc -O2 -shared -fPIC -o dither_native.so dither_native.c
 */

#include <math.h>

#define ERROR_CLAMP 96.0f

static inline float clamp_err(float e) {
    if (e > ERROR_CLAMP) return ERROR_CLAMP;
    if (e < -ERROR_CLAMP) return -ERROR_CLAMP;
    return e;
}

void floyd_steinberg(float *pixels, int width, int height) {
    for (int y = 0; y < height; y++) {
        int reverse = (y & 1);
        int start = reverse ? width - 1 : 0;
        int stop  = reverse ? -1 : width;
        int d     = reverse ? -1 : 1;

        for (int x = start; x != stop; x += d) {
            int idx = y * width + x;
            float old = pixels[idx];
            float new_val = (old >= 128.0f) ? 255.0f : 0.0f;
            pixels[idx] = new_val;
            float err = clamp_err(old - new_val);

            int xa = x + d;
            int xb = x - d;

            if (xa >= 0 && xa < width)
                pixels[idx + d] += err * 0.4375f;
            if (y + 1 < height) {
                int nr = (y + 1) * width;
                if (xb >= 0 && xb < width)
                    pixels[nr + xb] += err * 0.1875f;
                pixels[nr + x] += err * 0.3125f;
                if (xa >= 0 && xa < width)
                    pixels[nr + xa] += err * 0.0625f;
            }
        }
    }
}

void sierra_lite(float *pixels, int width, int height) {
    for (int y = 0; y < height; y++) {
        int reverse = (y & 1);
        int start = reverse ? width - 1 : 0;
        int stop  = reverse ? -1 : width;
        int d     = reverse ? -1 : 1;

        for (int x = start; x != stop; x += d) {
            int idx = y * width + x;
            float old = pixels[idx];
            float new_val = (old >= 128.0f) ? 255.0f : 0.0f;
            pixels[idx] = new_val;
            float err = clamp_err(old - new_val);

            int xa = x + d;
            int xb = x - d;

            if (xa >= 0 && xa < width)
                pixels[idx + d] += err * 0.5f;
            if (y + 1 < height) {
                int nr = (y + 1) * width;
                if (xb >= 0 && xb < width)
                    pixels[nr + xb] += err * 0.25f;
                pixels[nr + x] += err * 0.25f;
            }
        }
    }
}

void atkinson(float *pixels, int width, int height) {
    for (int y = 0; y < height; y++) {
        int reverse = (y & 1);
        int start = reverse ? width - 1 : 0;
        int stop  = reverse ? -1 : width;
        int d     = reverse ? -1 : 1;

        for (int x = start; x != stop; x += d) {
            int idx = y * width + x;
            float old = pixels[idx];
            float new_val = (old >= 128.0f) ? 255.0f : 0.0f;
            pixels[idx] = new_val;
            float err8 = clamp_err(old - new_val) * 0.125f;

            int xa1 = x + d;
            int xa2 = x + d * 2;
            int xb  = x - d;

            if (xa1 >= 0 && xa1 < width)
                pixels[idx + d] += err8;
            if (xa2 >= 0 && xa2 < width)
                pixels[idx + d * 2] += err8;
            if (y + 1 < height) {
                int nr = (y + 1) * width;
                if (xb >= 0 && xb < width)
                    pixels[nr + xb] += err8;
                pixels[nr + x] += err8;
                if (xa1 >= 0 && xa1 < width)
                    pixels[nr + xa1] += err8;
            }
            if (y + 2 < height) {
                pixels[(y + 2) * width + x] += err8;
            }
        }
    }
}
