FROM continuumio/miniconda3
RUN apt-get update && apt-get install -y build-essential redis-tools default-libmysqlclient-dev

# Python packages
RUN conda install -c conda-forge passlib flask-login flask-wtf flask-mail celery requests
RUN pip install flask-bcrypt flask-recaptcha mysqlclient

RUN pip install pyqrcode rauth pypng mailchimp3 python-dateutil==2.5.0 pycryptodome==3.4.3

RUN pip install --upgrade pip

COPY requirements.txt /back-end/requirements.txt
RUN pip install -r /back-end/requirements.txt
RUN conda install -c conda-forge uwsgi libiconv

ADD . /back-end

WORKDIR /back-end

COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]