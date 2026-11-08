"""Process exit codes, so a scheduler or a script can tell the outcomes apart.

    0  success   every source that was searched was read completely
    1  failure   no source could be read, or the run could not start (bad settings, crash)
    2  partial   some sources were read and some were not; the results are usable but incomplete
    3  busy      another scan is already running in this folder; nothing was changed
"""

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_PARTIAL = 2
EXIT_BUSY = 3

_BY_OVERALL_STATUS = {
    "success": EXIT_SUCCESS,
    "partial": EXIT_PARTIAL,
    "failure": EXIT_FAILURE,
}


def exit_code_for_overall_status(overall_status: str) -> int:
    """Map the overall status of a scan ('success', 'partial', 'failure') to an exit code."""
    return _BY_OVERALL_STATUS.get(overall_status, EXIT_FAILURE)
