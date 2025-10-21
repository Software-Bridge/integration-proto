#!/usr/bin/env python
import argparse
import json
import json2xml
import os
import csv
from datetime import datetime

def main():

    # ~/dev/fprime % vi ./MyProject/build-artifacts/Darwin/Myproject_HelloWorldDeployment/dict/HelloWorldDeploymentTopologyDictionary.json

    parser = argparse.ArgumentParser(description='Integration')
    parser.add_argument(
        '-i', 
        '--input', 
        dest='input_file', 
        required=True, 
        help='input file: type is of JSON and is required')

    args = parser.parse_args()
    
    channel_array = []
    states_array = []

    with open(args.input_file, 'r') as file:
            
            

            for line in file:
                try:
                    line = line.strip()
                    json_str = json.loads(line)
                    channel_array.append(json_str)
                except:
                    print("failed " + line + "\n")
                    pass

            for channel in channel_array:
                state = {}

                state["name"] = channel["name"]
                time = channel["time"]

                d = datetime.strptime(time, "%Y-%m-%dT%H:%M:%S.%f")
                # 2025-10-03T08:40:53.218673

                scet = d.strftime("%Y-%jT%H:%M:%S.%f")

                state["scet"] = scet

                state["value"] = channel["display_text"]

                print (state)                

                states_array.append(state)

    file.close()

    print("states array")
    print(states_array)
    
    with open("dan1.csv", 'w', newline='') as csvfile:
        

        header = "name,scet,value\n"
            
        csvfile.write(header)
        for row in states_array:
             print (row)
             vals = row["name"] + "," + row["scet"] + "," + str(row["value"]) + "\n"
             print (vals)
             csvfile.write(vals)

    csvfile.close()


if __name__ == '__main__':
    main()