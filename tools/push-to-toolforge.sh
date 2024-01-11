#!/bin/bash

pscp ../{criteria.py,app.py,list-users-for-review-rights.py,Pipfile,Pipfile.lock} countcount@login.toolforge.org:/data/project/flaggedrevspromotioncheck/www/python/src/
plink countcount@login.toolforge.org become flaggedrevspromotioncheck  webservice --backend=kubernetes python3.7 restart
