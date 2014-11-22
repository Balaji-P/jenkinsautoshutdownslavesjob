#!/bin/bash

set -x

echo "Starting slave and connecting..."
~/bin/slave.py up --instance_name=$1
echo 'Connecting...'

# SSH into the slave, grab the latest slave.jar from the master, and run it.
ssh $1 "
  curl http://your-jenkins-master/jnlpJars/slave.jar > ~/bin/slave.jar &&
  exec java -Xms1024m -Djava.awt.headless=true -jar ~/bin/slave.jar
  "
