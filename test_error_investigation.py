# test_error_investigation.py
import os
os.environ["AWS_PROFILE"] = "USMG-TST-MA-PROVIDER-QE-084828583690"

from resources.utils.scheduler_db_validation import validate_split_sub_processes

# Pick a real split_process_id you know has some failures
SPLIT_ID = "015e2d9b-aee6-4552-a723-a269c12a4d61"

result = validate_split_sub_processes(SPLIT_ID)

print("\n" + "="*60)
print(f"Split:     {result['split_process_id']}")
print(f"Status:    {result['status']}")
print(f"Completed: {result['completed']}")
print(f"Errored:   {result['errored']}")
print(f"Stuck:     {result['stuck']}")
print("="*60)

for err in result["error_details"][:3]:
    print(f"\n{err['sub_process']} | {err['business_value']}")
    print(f"  error: {err['raw_error']}")
    print(f"  reason: {str(err['detailed_reason'])[:200]}")
