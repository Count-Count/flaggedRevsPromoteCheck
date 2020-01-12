#!/bin/bash

pscp ../{criteria.py,app.py,Pipfile,Pipfile.lock} countcount@login.tools.wmflabs.org:/data/project/flaggedrevspromotioncheck/www/python/src/
plink countcount@login.tools.wmflabs.org become flaggedrevspromotioncheck  webservice --backend=kubernetes python3.7 restart
