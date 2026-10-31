"""Keep the AppImage mount alive through the tray for all real GUI launches."""
import sys
from . import cli


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    args = cli.parser().parse_args(arguments)
    if args.command in (None, 'gui') and not args.demo:
        arguments = (['--config', args.config] if args.config else []) + ['tray', '--open-settings']
    return cli.main(arguments)


if __name__ == '__main__':
    raise SystemExit(main())
