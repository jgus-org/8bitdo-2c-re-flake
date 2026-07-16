"""Brand the model name Ultimate->Ultima+e (ASCII + UTF-16LE) so a flashed pad reads distinctly in lsusb / the OS. Keep the length: the firmware returns each descriptor at a fixed code-level length, so a longer name truncates."""


def patch(d):
    hits = 0
    for old, new in ((b"Ultimate", b"Ultima+e"), ("Ultimate".encode("utf-16-le"), "Ultima+e".encode("utf-16-le"))):
        start = 0
        while (i := d.find(old, start)) >= 0:
            d[i:i + len(old)] = new
            start = i + len(old)
            hits += 1
    assert hits, "no 'Ultimate' brand string found"
