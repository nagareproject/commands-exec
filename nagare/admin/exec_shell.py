# --
# Copyright (c) 2008-2019 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

"""The ``shell`` and ``batch`` administrative commands

The ``shell`` command launches an interactive Python shell.
The ``batch`` command execute Python statements from a file.

In both cases:

  - the global variable ``apps`` is a dictionary of application name -> application object
  - the global variable ``session`` is the database session
  - the metadata of the applications are activated
"""

import os
import sys
import code
try:
    import __builtin__ as builtins
except ImportError:
    import builtins

from nagare.server import reference
from nagare.admin import admin, command


class Commands(command.Commands):
    DESC = 'interactive and batch runtime subcommands'

# -----------------------------------------------------------------------------


class IPythonShell(object):
    """A IPython >= 5.0 interpreter
    """
    def __init__(self, ipython, banner, prompt, ns):

        class NagarePrompts(ipython.terminal.prompts.Prompts):
            def in_prompt_tokens(self, cli=None):
                return [
                    (ipython.terminal.prompts.Token.Prompt, 'Nagare%s [' % prompt),
                    (ipython.terminal.prompts.Token.PromptNum, str(self.shell.execution_count)),
                    (ipython.terminal.prompts.Token.Prompt, ']: '),
                ]

        self.shell = ipython.terminal.embed.InteractiveShellEmbed(banner1=banner, user_ns=ns, confirm_exit=False)
        self.shell.prompts = NagarePrompts(self.shell)

    def __call__(self):
        self.shell()


class PythonShell(code.InteractiveConsole):
    """A plain Python interpreter
    """
    def __init__(self, banner, prompt, ns):
        """Initialisation

        In:
          - ``banner`` -- banner to display
          - ``prompt`` -- name of the activated application
          - ``ns`` -- the namespace with the ``apps`` and ``session`` variables defined
        """
        code.InteractiveConsole.__init__(self, ns)
        self.banner = banner
        self.prompt = prompt

    def raw_input(self, prompt):
        return code.InteractiveConsole.raw_input(self, 'Nagare' + self.prompt + prompt)

    def __call__(self):
        try:
            self.interact(self.banner, exitmsg='')
        except TypeError as e:
            if 'exitmsg' in e.args[0]:
                self.interact(self.banner)
            else:
                raise


class PythonShellWithHistory(PythonShell):
    """A plain Python interpreter with a readline history
    """
    def __call__(self, readline):
        """Launch the interpreter

        In:
          - ``readline`` -- the ``readline`` module
          - ``banner`` -- banner to display
        """
        # Set completion on TAB and a dedicated commands history file
        readline.parse_and_bind('tab: complete')

        history_path = os.path.expanduser('~/.nagarehistory')

        if os.path.exists(history_path):
            readline.read_history_file(history_path)

        readline.set_history_length(200)

        PythonShell.__call__(self)

        readline.write_history_file(history_path)


def create_python_shell(plain, banner, prompt, **ns):
    """Shell factory

    Create a shell according to the installed modules (``readline`` and ``ipython``)

    In:
      - ``ipython`` -- does the user want a IPython shell?
      - ``banner`` -- banner to display
      - ``prompt`` -- name of the activated application
      - ``ns`` -- the namespace with the ``apps`` and ``session`` variables defined
    """
    if not plain:
        try:
            from ptpython import repl, prompt_style
        except ImportError:
            pass
        else:
            def configure(repl):
                class NagarePrompt(prompt_style.ClassicPrompt):
                    def in_tokens(self, cli):
                        return [(prompt_style.Token.Prompt, 'Nagare%s>>> ' % prompt)]

                repl.all_prompt_styles['nagare'] = NagarePrompt()
                repl.prompt_style = 'nagare'

            print(banner)

            repl.embed(
                globals(), ns,
                history_filename=os.path.expanduser('~/.nagarehistory'),
                configure=configure
            )
            return

        try:
            from bpython import curtsies, embed
        except ImportError:
            pass
        else:
            class FullCurtsiesRepl(curtsies.FullCurtsiesRepl):
                def __init__(self, config, *args, **kw):
                    config.hist_file = os.path.expanduser('~/.nagarehistory')
                    super(FullCurtsiesRepl, self).__init__(config, *args, **kw)

                @property
                def ps1(self):
                    return 'Nagare' + prompt + super(FullCurtsiesRepl, self).ps1

            curtsies.FullCurtsiesRepl = FullCurtsiesRepl

            embed(ns, banner=banner)
            return

        try:
            import IPython
        except ImportError:
            pass
        else:
            IPythonShell(IPython, banner, prompt, ns)()
            return

    try:
        import readline

        PythonShellWithHistory(banner, prompt, ns)(readline)
    except ImportError:
        PythonShell(banner, prompt, ns)()


class Shell(command.Command):
    DESC = 'launch an interactive shell'
    WITH_STARTED_SERVICES = True

    def set_arguments(self, parser):
        super(Shell, self).set_arguments(parser)
        parser.add_argument(
            '--plain', action='store_const', const=True, default=False, dest='plain',
            help='launch a plain Python interpreter instead of PtPython/BPython/IPython'
        )

    def run(self, services_service, plain=False):
        """Launch an interactive shell

        In:
          - ``parser`` -- the ``optparse.OptParser`` object used to parse the configuration file
          - ``options`` -- options in the command line
          - ``args`` -- arguments in the command line

        The arguments are a list of names of registered applications
        or paths to applications configuration files.
        """
        ns = {'services': services_service}
        for handler in services_service.interactive_handlers:
            ns.update(handler.handle_interactive())

        banner = admin.BANNER + '\n'
        banner += 'Python %s on %s\n\n' % (sys.version, sys.platform)

        if len(ns) == 1:
            banner += "Variable '%s' is available" % next(iter(ns))
        else:
            variables = ["'%s'" % variable for variable in sorted(ns)]
            banner += 'Variables ' + ', '.join(variables[:-1]) + ' and ' + variables[-1] + ' are available'

        banner += '\n'

        app = ns.get('app')

        create_python_shell(
            plain,
            banner,
            '' if app is None else ('[%s]' % app.name),
            __name__='__console__', **ns
        )

# -----------------------------------------------------------------------------


class Batch(command.Command):
    DESC = 'execute Python statements from a file'
    WITH_STARTED_SERVICES = True

    def set_arguments(self, parser):
        parser.add_argument('python_file', help='python batch file')
        super(Batch, self).set_arguments(parser)

    def run(self, python_file, services_service):
        """Execute Python statements from a file
        """
        ns = {'services': services_service}
        for handler in services_service.interactive_handlers:
            ns.update(handler.handle_interactive())

        builtins.__dict__.update(ns)

        reference.load_file(python_file, None)
