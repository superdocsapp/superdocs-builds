import time
import logging
import functools

logger = logging.getLogger(__name__)

def observe_node(cost_per_call=0.01):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(state):
            start_time = time.time()
            logger.info(f"--- [START] Node: {func.__name__} ---")
            
            result = func(state)
            
            end_time = time.time()
            elapsed = end_time - start_time
            logger.info(f"--- [END] Node: {func.__name__} | Time: {elapsed:.2f}s | Cost: ${cost_per_call:.4f} ---")
            
            return result
        return wrapper
    return decorator
