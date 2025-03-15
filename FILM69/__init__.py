import warnings
warnings.simplefilter("ignore", UserWarning)
from .DisPrint import dis_print

with dis_print():
    try:from .ml import *
    except:...
    from .datasets.clean_text import clean_text
    from .tts import TTS