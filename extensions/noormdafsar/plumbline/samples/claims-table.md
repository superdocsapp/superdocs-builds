| kind | symbol | parameter | value | quote |
| --- | --- | --- | --- | --- |
| constant\_value | DEFAULT\_TIMEOUT |  | 30 seconds | The default request timeout is 30 seconds, which is generous for most workloads. |
| constant\_value | MAX\_PAGE\_SIZE |  | 500 records | The maximum page size is 500 records. |
| constant\_value | DEFAULT\_REGION |  | eu-west-1 region | Requests are issued against the eu-west-1 region unless another is given. |
| parameter\_exists | Client.\_\_init\_\_ | region |  | The constructor also accepts region , timeout and max\_retries , which defaults to 5. |
| parameter\_exists | Client.\_\_init\_\_ | timeout |  | The constructor also accepts region , timeout and max\_retries , which defaults to 5. |
| parameter\_exists | Client.\_\_init\_\_ | max\_retries |  | The constructor also accepts region , timeout and max\_retries , which defaults to 5. |
| parameter\_default | Client.\_\_init\_\_ | max\_retries | 5 | The constructor also accepts region , timeout and max\_retries , which defaults to 5. |
| return\_type | Client.list\_ledgers |  | a list of dictionaries | Returns a list of dictionaries, newest first. |
| parameter\_exists | Client.list\_ledgers | page\_size |  | Pass page\_size to control how many come back; it defaults to 50. |
| parameter\_default | Client.list\_ledgers | page\_size | 50 | Pass page\_size to control how many come back; it defaults to 50. |
| parameter\_exists | Client.list\_ledgers | cursor |  | A cursor may be supplied to continue a previous page, and include\_archived pulls in ledgers that have been archived. |
| parameter\_exists | Client.list\_ledgers | include\_archived |  | A cursor may be supplied to continue a previous page, and include\_archived pulls in ledgers that have been archived. |
| raises | Client.list\_ledgers | page\_size | ValueError | If page\_size is larger than the maximum, the call raises ValueError . |
| return\_type | Client.get\_ledger |  | a dictionary | Fetches a single ledger by id and returns a dictionary. |
| raises | Client.get\_ledger |  | NotFound | Raises NotFound when no such ledger exists. |
| return\_type | Client.post\_entry |  | a dictionary | Appends an entry to a ledger and returns the created entry as a dictionary. |
| parameter\_exists | Client.post\_entry | currency |  | The currency argument defaults to USD. |
| parameter\_default | Client.post\_entry | currency | USD | The currency argument defaults to USD. |
| parameter\_exists | Client.post\_entry | idempotency\_key |  | Pass an idempotency\_key to make retries safe. |
| return\_type | Client.close\_ledger |  | a boolean | Closes a ledger and returns a boolean. |
| parameter\_exists | Client.close\_ledger | reason |  | A reason is required, and an effective\_date may be supplied to backdate the closure. |
| parameter\_exists | Client.close\_ledger | effective\_date |  | A reason is required, and an effective\_date may be supplied to backdate the closure. |
