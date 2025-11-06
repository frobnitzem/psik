# Valid backends must contain all the following function
# prototypes:
# 
# async def submit(job: Job, jobndx: int) -> Optional[str]
# async def cancel(jobinfos: List[str]) -> None
# async def poll(jobids: List[str]) -> List[JobState]
