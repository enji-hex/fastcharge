scp -r  .\fastcharge\src\*    root@107.189.20.194:/root/fastcharge/src/
scp -r  .\fastcharge\local\*  root@107.189.20.194:/root/fastcharge/local/
ssh root@107.189.20.194 "systemctl restart fastcharge"
