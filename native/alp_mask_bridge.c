/* Unix-socket token masks for MLX-Serve. Copyright 2026, Apache-2.0. */
#include <arpa/inet.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/time.h>
#include <unistd.h>

static int put32(FILE *f, uint32_t n) { n = htonl(n); return fwrite(&n, 4, 1, f) == 1; }
static int get32(FILE *f, uint32_t *n) { if (fread(n, 4, 1, f) != 1) return 0; *n = ntohl(*n); return 1; }

void *alp_mask_open(const char *grammar, size_t len, const char **tokens,
                    const size_t *lengths, size_t size, uint32_t eos) {
    const char *path = getenv("MLX_ALP_MASK_SOCKET");
    if (!path || strlen(path) >= sizeof(((struct sockaddr_un *)0)->sun_path)) return NULL;
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return NULL;
    struct timeval timeout = {60, 0};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
#ifdef SO_NOSIGPIPE
    int yes = 1;
    setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &yes, sizeof(yes));
#endif
    struct sockaddr_un addr = {0};
    addr.sun_family = AF_UNIX;
    strcpy(addr.sun_path, path);
    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) { close(fd); return NULL; }
    FILE *f = fdopen(fd, "r+");
    if (!f) { close(fd); return NULL; }
    setvbuf(f, NULL, _IOFBF, 128 * 1024);
    if (fwrite("ALP1", 1, 4, f) != 4 || !put32(f, (uint32_t)len) ||
        fwrite(grammar, 1, len, f) != len || !put32(f, (uint32_t)size) || !put32(f, eos)) goto failed;
    for (size_t i = 0; i < size; i++) {
        if (!put32(f, tokens[i] ? (uint32_t)lengths[i] : UINT32_MAX)) goto failed;
        if (tokens[i] && fwrite(tokens[i], 1, lengths[i], f) != lengths[i]) goto failed;
    }
    if (fflush(f) != 0 || fgetc(f) != 1) goto failed;
    return f;
failed:
    fclose(f);
    return NULL;
}

int alp_mask_fill(void *handle, unsigned char *mask, size_t size, int *complete) {
    FILE *f = handle;
    if (fputc('M', f) == EOF || fflush(f) != 0) return -1;
    int done = fgetc(f);
    uint32_t n = 0;
    if ((done != 0 && done != 1) || !get32(f, &n) || n != size || fread(mask, 1, size, f) != size) return -1;
    *complete = done;
    int count = 0;
    for (size_t i = 0; i < size; i++) { if (mask[i] > 1) return -1; count += mask[i]; }
    return count;
}

int alp_mask_accept(void *handle, uint32_t token) {
    FILE *f = handle;
    if (fputc('A', f) == EOF || !put32(f, token) || fflush(f) != 0) return 0;
    return fgetc(f) == 1;
}

void alp_mask_close(void *handle) { if (handle) fclose(handle); }
