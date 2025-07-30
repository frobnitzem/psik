# https://stackoverflow.com/questions/13733552/logger-configuration-to-log-to-file-and-print-to-stdout
import sys
import logging

# Logging formatter supporting colorized output
class LogFormatter(logging.Formatter):

    COLOR_CODES = {
        logging.CRITICAL: "\033[1;35m", # bright/bold magenta
        logging.ERROR:    "\033[1;31m", # bright/bold red
        logging.WARNING:  "\033[1;33m", # bright/bold yellow
        logging.INFO:     "\033[0;37m", # white / light gray
        logging.DEBUG:    "\033[1;30m"  # bright/bold dark gray
    }

    RESET_CODE = "\033[0m"

    def __init__(self, *args, color=False, **kwargs):
        super(LogFormatter, self).__init__(*args, **kwargs)
        self.color = color

    def format(self, record, *args, **kwargs):
        if (self.color and record.levelno in self.COLOR_CODES):
            record.color_on  = self.COLOR_CODES[record.levelno]
            record.color_off = self.RESET_CODE
        else:
            record.color_on  = ""
            record.color_off = ""
        return super(LogFormatter, self).format(record, *args, **kwargs)

def setup_log(color_console = True,
              v=False, vv=False
             ):
    log_level=logging.WARNING
    if v:
        log_level=logging.INFO
    elif vv:
        log_level=logging.DEBUG

    logger = logging.getLogger()
    # Set global log level to 'debug' (required for handler levels to work)
    logger.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    # Create and set formatter, add console handler to logger
    console_formatter = LogFormatter(color=color_console)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

def setup_logfile(logfile, v=False, vv=False):
    if logfile is None:
        return

    log_level=logging.WARNING
    if v:
        log_level=logging.INFO
    elif vv:
        log_level=logging.DEBUG

    logger = logging.getLogger()
    # Set global log level to 'debug' (required for handler levels to work)
    logger.setLevel(logging.DEBUG)

    logfile_handler = logging.FileHandler(logfile)
    logfile_handler.setLevel(log_level)

    logfile_formatter = LogFormatter()
    logfile_handler.setFormatter(logfile_formatter)
    logger.addHandler(logfile_handler)
