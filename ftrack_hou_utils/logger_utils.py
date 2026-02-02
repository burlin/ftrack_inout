import logging

def get_logger(name="ftrack_hda", level=logging.INFO):
    """
    Stub function for get_logger.
    Returns a basic logger to avoid errors.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger 