# rtsp_ws
Websocket server that serves metadata in V2X expected format

Update ENV with rtsp link in docker file as needed
# Topic value configuration
"tns1:IVA/EnteringField/value" : The "EnteringField" Topic has been configured with Entering_field as "value" in configuration manager, if there is a change in this name, need to update "value" in main under the _process_metadata function
"tns1:IVA/LeavingField/value" : The "LeavingField" Topic has been configured with Leaving_field as "value" in configuration manager, if there is a change in this name, need to update "value" in main under the _process_metadata function

In case there is a need to use ObjectInField Topic, _process_metadata can be changed accordingly to use it instead of EnteringField

# Docker commands to setup container
docker build -t websocket-server .
docker run -p 8080:80 websocket-server