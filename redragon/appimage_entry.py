"""Launch the foreground app; its mount is released when the window closes."""
import sys
from . import cli


def main(argv=None):
    return cli.main(list(sys.argv[1:] if argv is None else argv))


if __name__ == '__main__':
    raise SystemExit(main())
