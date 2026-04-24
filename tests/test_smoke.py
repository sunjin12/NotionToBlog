import re

import dayblog
import dayblog_mcp


def test_dayblog_version_is_pep440_like():
    assert isinstance(dayblog.__version__, str)
    assert re.match(r"^\d+\.\d+\.\d+", dayblog.__version__)


def test_dayblog_mcp_reexports_same_version():
    assert dayblog_mcp.__version__ == dayblog.__version__
