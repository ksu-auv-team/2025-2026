For changes to apply to original branch git push origin Eyasu-HWI-updates

For the orin use requirements.txt 
working with the software module use the the dev requirements 
created the Hardware interface requirements file 


hardware_interface.py code review 

to_add return int function
    - returns an integer representation of the value in this case string 
        + int(value,base)
            1. This function converts the value to an int and the second specifies the base. 
            * 0 is used to automatically detect the base 

conditional statement that only converts 
    


What is a bus?
A bus is type of communication system that does data transfer between components within a computer. Reduces the number of connections needed by centralizing communication over shared pathways

More about the computer bus.
    - The size of the bus determines how much information can be sent 
    Types of busses 
        1.address bus 
            + single directional
            + sends address signals from cpu to main memory (main memory is the ram)
            + these address signals contain specific address locations from main memory
            +identifies where data should go 

    
probe_i2c_rdwr method 

parameters 
    bus, the location of the i2c, the amount of bits to read and returns a tuple of a boolean and optional string 
    exception block 
        .i2c_msg function is taking the address and the amount of bits to read from that address 
        the i2c_rdwr takes these instructions and sends the message to the i2c device and actually communicates 
        return type shares success and the error 
        Is it guranteed that it will go to the correct address 



hardware interface class 

load in hardware config as a dictionary: 

gather the set that you want to skip values 
create a new dict comprehension or return an empty set 


Questions what are the M1 

Essentially create a list of values to to skip including the motor controller.
    This dict includes the addresses of the hardware 

Call check_hardware_addresses method 
    Calls the config_address() method and loops through it 

    config_addresses method 
        returns a list of addresses that are correct 

Check_hardware question
    why for the config_address method add keys of values to skip
    why not just only include the keys that want to be used? 
    I think this is used to make sure skipped values will not be added(another checkpoint)
    
    for the non-skipped addresses 
        return the boolean, None or if failed return the error 

We take in the input data
IMU information 

Serial IMU(pico running arduino sketch)
    - sketch is another name for arduino program 

Check for serial connect failure 

Ask to explain 90-117

Qualifications method 
    Some sort've setup stage 
    motors dict with initial values and these get sent to the motor controller 
    - If this is an error it will be shared 
    the motors dict changes to new values and these values get sent to the motor 

Qualification summary
    - motor validation before deployment 
    - pre made movements 
_MotorController method 
    role: sends motor control data to the motor controller as bytes in hex  


Decorators 
- extends a base class without changing the base function's abilities 
@static method 
a method that can be called without an instance and doesn't have the receiver object 
meaning it doesn't belong to a specific class 


PWM -> Pulse width modulation 
    responsible for the speed of the motors 
    There is an on and off pattern | the different percentages describe how on or off something is 


Logic.py 


sending data to the database 
    

getting data from the database 
    requests.get(url)
        In our instance the url will be the correct path. So no param argument is needed 


SplitData function 
    separating the motor data, torpedoes, and motors 
    returns a tuple of dicts


Notation 0..255 THe double decimals shares that this is a range 


Data Process Handling 

Serial IMU to API
    Stores the data with several types of values like X, Y, Z, Roll, pitch, YAW
        This gets posted to the database API: path = db/db_port/IMU


Yaw = rotation z axis 
pitch = rotation y 
roll = rotation x 