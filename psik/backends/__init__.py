# Valid backends must contain all the following function
# prototypes:
# 
# async def submit(job: Job, jobndx: int) -> Optional[str]
# async def cancel(job: Job) -> None
# async def poll(job: Job) -> None
