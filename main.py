import asyncio
import websockets
import os
import json
import xml.etree.ElementTree as ET
import math
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst



Gst.init(None)
frame_sample_buffer = []  # Buffer to keep samples until the entire frame is available
object_tracking_buffer = []  # Buffer to keep track of objects
object_info_tracking_stack = {}

dataNumber = 1

async def handle_websocket(websocket, path):
    try:
        print(f"Client connected from {websocket.remote_address}", flush=True)
        
        # Send the initial response expected from v2x upon client connection
        initial_response = {
            "messageType": "Subscription",
            "subscription": {
                "returnValue": "OK",
                "type": "Data"
            }
        }
        await websocket.send(json.dumps(initial_response))
        
        # GStreamer pipeline creation and connection logic
        rtsp_url = os.getenv("RTSP_URL")
        pipeline_str = f"rtspsrc location={rtsp_url} ! application/x-rtp, media=application, payload=107, encoding-name=VND.ONVIF.METADATA! rtpjitterbuffer ! appsink name=appsink"
        pipeline = Gst.parse_launch(pipeline_str)

        # Connect to the EOS (end-of-stream) signal
        bus = pipeline.get_bus()
        bus.set_sync_handler(on_bus_message_sync, {"websocket": websocket, "pipeline": pipeline})

        pipeline.set_state(Gst.State.PLAYING)

        try:
            # Retrieve the appsink element from the pipeline
            appsink = pipeline.get_by_name("appsink")
            appsink.set_property("emit-signals", True)

            # Connect the new-sample signal to a callback function
            appsink.connect("new-sample", on_new_sample, {"websocket": websocket, "loop": asyncio.get_event_loop()})
                
            while True:
                await asyncio.sleep(0.1)
        # finally:
        #     # Cleanup GStreamer pipeline
        #     pipeline.set_state(Gst.State.NULL)
        except websockets.ConnectionClosedError:
            print("Client disconnected", flush=True)
    except Exception as e:
        print(f"An error occurred in handle_websocket: {e}", flush=True)

def on_bus_message_sync(bus, message, data):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(on_bus_message(bus, message, data))
    loop.close()
    return Gst.BusSyncReply.PASS

async def on_bus_message(bus, message, data):
    print(f"Received message: {message.type}",flush=True)
    try:
        # Handle GStreamer bus messages asynchronously
        if message.type == Gst.MessageType.EOS:
            print("End of stream message received.",flush=True)
            # Perform any cleanup or additional actions here
            # _terminate_socket_connection(data)
            # data["websocket"].close()
            print("Before awaiting reset_pipeline", flush=True)
            await reset_pipeline(data["pipeline"])
            print("After awaiting reset_pipeline", flush=True)
            # data["pipeline"].set_state(Gst.State.PLAYING)
        elif message.type == Gst.MessageType.ERROR:
            error, debug_info = message.parse_error()
            print(f"Error: {error}, Debug Info: {debug_info}",flush=True)
            # data["websocket"].close()
    except Exception as e:
        print(f"An unexpected error occurred in on_bus_message: {e}", flush=True)
    return True

async def reset_pipeline(pipeline):
    print("Reset pipeline function triggered",flush=True)
    try:
        # Cleanup existing GStreamer pipeline
        # Before handling EOS
        # print("Pipeline state before handling EOS:", pipeline.get_state(0)[1].value_name)

        pipeline.set_state(Gst.State.NULL)

        #  additional logic for reconnection if needed

        # Waiting for a few seconds before attempting to reconnect
        # print("Before sleep", flush=True)
        await asyncio.sleep(2)
        # print("After sleep", flush=True)

        # Reconnect by transitioning back to the PLAYING state
        pipeline.set_state(Gst.State.PLAYING)
        # print("Pipeline After before handling EOS 3:", pipeline.get_state(0)[1].value_name)
    except Exception as e:
        print(f"An unexpected error occurred in reset_pipeline: {e}", flush=True)
        raise


async def _terminate_socket_connection(data):
    await data["websocket"].close()

def on_new_sample(appsink, data):
    try:
        sample = appsink.emit("pull-sample")
        if sample:
            buffer = sample.get_buffer()
            payload_size = buffer.get_size()
            payload_data = buffer.extract_dup(0, payload_size)

            rtp_header = payload_data[:12]
            timestamp = int.from_bytes(rtp_header[4:8], byteorder='big')
            sequence_number = int.from_bytes(rtp_header[2:4], byteorder='big')
            paload_body = payload_data[12:]
            decoded_data = paload_body.decode('UTF-8')
            
            if _is_complete_metadata_frame(decoded_data):
                frame_sample_buffer.append(decoded_data)
                combined_metadata = "".join(frame_sample_buffer)
                frame_sample_buffer.clear()

                loop = data["loop"]
                websocketserver = data["websocket"]
                _process_metadata(combined_metadata, loop, websocketserver)
            else:
                frame_sample_buffer.append(decoded_data)
    except Exception as e:
        print(f"An error occurred in on_new_sample: {e}", flush=True)
    return Gst.FlowReturn.OK

def _is_complete_metadata_frame(data):
    return data.endswith("</tt:MetadataStream>")

def _process_metadata(data, loop, websocketserver):
    # print(data,flush=True)
    try:
        # Tracking Notification Topics 
        entering_topic = "tns1:IVA/EnteringField/Entering_field"
        leaving_topic = "tns1:IVA/LeavingField/Leaving_field"
        infield_topc = "tns1:IVA/ObjectInField/Object_in_Field_1"

        data_by_object_id = {}
        
        root = ET.fromstring(data)
        
        for notification_message in root.findall('.//wsnt:NotificationMessage', namespaces={'wsnt': 'http://docs.oasis-open.org/wsn/b-2'}):
            topic = notification_message.find('./wsnt:Topic', namespaces={'wsnt': 'http://docs.oasis-open.org/wsn/b-2'}).text

            if topic == infield_topc:
                _process_entering_object(notification_message)

            elif topic == leaving_topic:
                _process_leaving_object(notification_message)

        if len(object_info_tracking_stack) > 0:
            for target_object_id in object_info_tracking_stack:
                object_data = _extract_object_data(root, target_object_id)

                if object_data:
                    data_by_object_id[target_object_id] = object_data

        _send_data_to_client(loop, websocketserver, data_by_object_id)
    
    except ET.ParseError as parse_error:
        print(f"Error parsing XML data: {parse_error}",flush=True)
    except KeyError as key_error:
        print(f"KeyError: {key_error}",flush=True)
    except Exception as e:
        print(f"An unexpected error occurred in _process_metadata: {e}",flush=True)

def _process_entering_object(notification_message):
    try:
        entering_object_keys = notification_message.find(".//tt:Message/tt:Key", namespaces={"tt": "http://www.onvif.org/ver10/schema"})
        for key_element in entering_object_keys:
            value = key_element.get("Value")
            object_tracking_buffer.append(value)
            if value not in object_info_tracking_stack:
                object_info_tracking_stack[value] = {"initial_heading_x": None, "initial_heading_y": None}
    except Exception as e:
        print(f"An error occurred in _process_entering_object: {e}",flush=True)

def _process_leaving_object(notification_message):
    try:
        exiting_object_keys = notification_message.find(".//tt:Message/tt:Key", namespaces={"tt": "http://www.onvif.org/ver10/schema"})
        if exiting_object_keys:
            for key_element in exiting_object_keys:
                value = key_element.get("Value")
                object_tracking_buffer.remove(value)
                object_info_tracking_stack.pop(value)
    except Exception as e:
        print(f"An error occurred in _process_leaving_object: {e}",flush=True)

def _extract_object_data(root, target_object_id):
    try:
        object_data = {}
        
        for object_elem in root.findall(".//tt:Object", namespaces={"tt": "http://www.onvif.org/ver10/schema"}):
            if object_elem.get("ObjectId") == target_object_id:
                utc_time = root.find(".//tt:Frame", namespaces={"tt": "http://www.onvif.org/ver10/schema"}).get('UtcTime')
                if utc_time:
                    object_data["utc_time"] = utc_time[:-1]
                
                center_of_gravity_elem = object_elem.find(".//tt:CenterOfGravity", namespaces={"tt": "http://www.onvif.org/ver10/schema"})
                if center_of_gravity_elem is not None:
                    object_data["x"] = center_of_gravity_elem.get("x")
                    object_data["y"] = center_of_gravity_elem.get("y")
                    
                    if object_info_tracking_stack[target_object_id]["initial_heading_x"] is None:
                        object_info_tracking_stack[target_object_id]["initial_heading_x"] = center_of_gravity_elem.get("x")
                    
                    if object_info_tracking_stack[target_object_id]["initial_heading_y"] is None:
                        object_info_tracking_stack[target_object_id]["initial_heading_y"] = center_of_gravity_elem.get("y")
                    
                    object_data["Heading"] = math.degrees(math.atan2(
                        float(center_of_gravity_elem.get("y")) - float(object_info_tracking_stack[target_object_id]["initial_heading_y"]),
                        float(center_of_gravity_elem.get("x")) - float(object_info_tracking_stack[target_object_id]["initial_heading_y"])))

                class_candidate_elem = object_elem.find(".//tt:ClassCandidate", namespaces={"tt": "http://www.onvif.org/ver10/schema"})
                if class_candidate_elem is not None:
                    # object_data["ClassCandidate"] = {
                    #     "type": class_candidate_elem.find(".//tt:Type", namespaces={"tt": "http://www.onvif.org/ver10/schema"}).text,
                    #     "likelihood": class_candidate_elem.find(".//tt:Likelihood", namespaces={"tt": "http://www.onvif.org/ver10/schema"}).text,
                    # }
                    object_data["class_candidate_type"] = class_candidate_elem.find(".//tt:Type", namespaces={"tt": "http://www.onvif.org/ver10/schema"}).text
                    object_data["likelihood"] = class_candidate_elem.find(".//tt:Likelihood", namespaces={"tt": "http://www.onvif.org/ver10/schema"}).text
                
                # type_elem = object_elem.find(".//tt:Type",namespaces={"tt": "http://www.onvif.org/ver10/schema"})
                # if type_elem is not None:
                #     object_data["type"] = type_elem.text

                # latitude_elem = root.find(".//tt:Extension/NavigationalData/Latitude", namespaces={"tt": "http://www.onvif.org/ver10/schema"})
                # if latitude_elem is not None:
                #     object_data["latitude"] = latitude_elem.text

                # longitude_elem = root.find(".//tt:Extension/NavigationalData/Longitude", namespaces={"tt": "http://www.onvif.org/ver10/schema"})
                # if longitude_elem is not None:
                #     object_data["longitude"] = longitude_elem.text

                geolocation_elem = object_elem.find(".//tt:GeoLocation", namespaces={"tt": "http://www.onvif.org/ver10/schema"})
                if geolocation_elem is not None:
                    object_data["latitude"] = geolocation_elem.get("lat")
                    object_data["longitude"] = geolocation_elem.get("lon")
                    object_data["elevation"] = geolocation_elem.get("elevation")


                speed_elem = object_elem.find(".//tt:Speed", namespaces={"tt": "http://www.onvif.org/ver10/schema"})
                if speed_elem is not None:
                    object_data["Speed"] = speed_elem.text

                break
    except Exception as e:
        print(f"An error occurred in _extract_object_data: {e}",flush=True)

    return object_data

def _send_data_to_client(loop, websocketserver, data_by_object_id):
    try:
        for object_id, value in data_by_object_id.items():
            global dataNumber
            print(object_id,flush=True)
            print(value.get("class_candidate_type"),flush=True)
            if value.get("utc_time") and value.get("class_candidate_type") == "Human":
                metadata_dict = {
                    "dataNumber": dataNumber,
                    "messageType": "Data",
                    "time": value.get("utc_time"),
                    "track": [
                        {
                            "angle": value.get("Heading"),
                            "class": "Pedestrian",
                            "iD": object_id,
                            "latitude": value.get("latitude"),
                            "longitude": value.get("longitude"),
                            "speed": value.get("Speed"),
                            "x": value.get("x"),
                            "y": value.get("y")
                        }
                    ],
                    "type": "PedestrianPresenceTracking"
                }
                dataNumber = dataNumber + 1
                loop.create_task(send_message(websocketserver, metadata_dict))
    except Exception as e:
        print(f"An error occurred in _send_data_to_client: {e}",flush=True)

async def send_message(websocket, payload_data):
    try:
        await websocket.send(json.dumps(payload_data))
    except Exception as e:
        print(f"An error occurred in send_message: {e}", flush=True)

if __name__ == "__main__":
    try:
        start_server = websockets.serve(handle_websocket, "0.0.0.0", 80)

        asyncio.get_event_loop().run_until_complete(start_server)
        print("WebSocket server running at ws://0.0.0.0:80", flush=True)

        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        print("WebSocket server stopped", flush=True)
    except Exception as e:
        print(f"An error occurred: {e}", flush=True)
