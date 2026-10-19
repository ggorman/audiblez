# -*- coding: utf-8 -*-
import argparse
import sys

from audiblez.voices import voices, available_voices_str


def cli_main():
    voices_str = ', '.join(voices)
    epilog = ('example:\n' +
              '  audiblez book.epub -v af_sky\n'
              '  audiblez summary.md -v bf_emma --author "Jane Doe"\n\n' +
              'to run GUI just run:\n'
              '  audiblez-ui\n\n' +
              'available voices:\n' +
              available_voices_str)
    default_voice = 'af_sky'
    parser = argparse.ArgumentParser(epilog=epilog, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('epub_file_path', help='Path to an .epub, .md or .txt file')
    parser.add_argument('-v', '--voice', default=default_voice, help=f'Choose narrating voice: {voices_str}')
    parser.add_argument('-p', '--pick', default=False, help=f'Interactively select which chapters to read in the audiobook', action='store_true')
    parser.add_argument('-s', '--speed', default=1.0, help=f'Set speed from 0.5 to 2.0', type=float)
    parser.add_argument('-c', '--cuda', default=False, help=f'Use GPU via Cuda in Torch if available', action='store_true')
    parser.add_argument('-o', '--output', default='.', help='Output folder for the audiobook and temporary files', metavar='FOLDER')
    parser.add_argument('--title', help='Audiobook title (overrides the book metadata)')
    parser.add_argument('--author', help='Audiobook author (overrides the book metadata)')

    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)
    args = parser.parse_args()

    if args.cuda:
        import torch.cuda
        if torch.cuda.is_available():
            print('CUDA GPU available')
            torch.set_default_device('cuda')
        else:
            print('CUDA GPU not available. Defaulting to CPU')

    from core import main
    main(args.epub_file_path, args.voice, args.pick, args.speed, args.output, title=args.title, author=args.author)


if __name__ == '__main__':
    cli_main()
