#!/usr/bin/python

import rospy
#from swarmflock.msg import WiFiRSSIMsg
from swarmflock.srv import *
import wifiutils
#import hotspot
import sys, cli
import os, time, math
from scapy.all import sniff, Dot11, get_if_hwaddr, send, IP, ICMP
from pythonwifi.iwlibs import Wireless, Iwrange
from netaddr import OUI
from itertools import groupby
from operator import itemgetter
from WiFiTrilatClient import WiFiTrilatClient


class WiFiTrilatSrv:

  def handler(self, packet):
    if packet.haslayer(Dot11):
      # Check to make sure this is a management frame (type=0) and that
      # the subtype is one of our management frame subtypes indicating a
      # a wireless client
      #if packet.addr2 and packet.addr2.lower() == self.mac:
      if packet.addr2:
        rssi = self.siglevel(packet)# if self.siglevel(packet)!=-256 else -100
        self.msgs.append((packet.addr2.lower(), rssi))




  def patience_call(self, event):
    self.msgs.sort()
    byMAC = groupby(self.msgs, lambda x: x[0])

    for key, group in byMAC:
      mac = key
      rssis = [p[1] for p in group if p[1] > -230]

      if len(rssis) == 0:
        continue

      avg = sum(rssis) / len(rssis)
      self.distances.append((mac, wifiutils.calcDistance(avg, self.freq), time.time()))


    self.msgs = []



  def distPurge(self, event):
    rospy.loginfo("Purging distances. Currently have " + str(len(self.distances)))

    now = time.time()
    self.distances = [x for x in self.distances if x[2] + self.tolerance > now]
    self.distances = sorted(self.distances, key=itemgetter(2))

    rospy.loginfo("Distances purged! Now have " + str(len(self.distances)))




  def handle_Trilat(self, req):
    distances = [x for x in self.distances if x[0] == req.mac_address and math.fabs(req.time - x[2]) <= req.tolerance]
    numElem = len(distances)

    if numElem > 0:
      return WiFiTrilatResponse(self.robotName, distances[numElem - 1][1], distances[numElem - 1][2], self.x, self.y)
    else:
      return WiFiTrilatResponse(self.robotName, -1, -1, self.x, self.y)



  # This function will attempt to find this server's position relative to the other servers.
  def findSelfPos(self, event):
    mac = get_if_hwaddr(self.interface)
    servers = self.client.discover()

    while(len(servers) < 3):
      rospy.loginfo("Found only " + str(len(servers)) + " servers!")
      rospy.sleep(1)
      servers = self.client.discover()

    otherServers = [x for x in servers if x.find(self.robotName) == -1]

    # This will call the other servers' WiFiTrilatServices. To do this, we enter our own MAC address,
    # then take two servers that are NOT ours.
    responses = self.client.getDistances(mac, otherServers)
    #goodServers = [x.srv_name for x in responses if x.distance != -1]
    goodResponses = [x for x in responses if x.distance != -1]

    for x in responses:
      print x.srv_name
      print x.distance
    goodServers = sorted([x.srv_name for x in goodResponses])

    for x in goodServers:
      print x

    if len(goodServers) < 2:
      rospy.loginfo("Not enough servers!")
      return

    #serverNames = sorted([s[1:s.find('/WiFi')] for s in servers])
    index = goodServers.index(self.robotName)

    # Next we need to find the distance between the two other servers

    print "Host 0 is " + goodServers[0]
    print "Host 1 is " + goodServers[1]
    goodResponses.append(self.client.getDistances(self.client.IPtoMAC(self.client.hostToIP(goodServers[0])), goodServers[1]))

    # We take our relative position based on alphabetical order.
    [self.x, self.y] = wifiutils.calcFrameOfRef(goodResponses[0].distance, goodResponses[2].distance, goodResponses[1].distance)[index]




  def __init__(self, interface, freq, essid, psswd, ip, nm, discoverOnce=True):
    self.robotName = os.getenv('HOSTNAME')
    self.tolerance = 10
    self.x = 0
    self.y = 0
    self.client = WiFiTrilatClient()

    rospy.init_node(self.robotName + "_wifitrilat_server")

    #self.rssiPub = rospy.Publisher('/' + self.robotName + '/WiFiRSSI', WiFiRSSIMsg, queue_size=10)
    self.service = rospy.Service("/" + self.robotName + "/WiFiTrilat", WiFiTrilat, self.handle_Trilat)

    self.interface = interface
    #self.mac = mac.lower()
    self.freq = int(freq)

    self.msgs = []
    self.distances = []

    cli.execute_shell("ifconfig %s down" % self.interface)
    self.wifi = Wireless(self.interface).setFrequency("%.3f" % (float(self.freq) / 1000))
    self.connectToNet(essid, psswd,ip, nm)

    self.patience = rospy.Timer(rospy.Duration(2), self.patience_call)
    self.purge = rospy.Timer(rospy.Duration(2), self.distPurge)
    self.heartbeat = rospy.Timer(rospy.Duration(1), self.heartbeat_call)

    if discoverOnce:
      self.findSelfPos(None)
    else:
      self.discoverTimer = rospy.Timer(rospy.Duration(2), self.findSelfPos)


    sniff(iface=self.interface, prn=self.handler, store=0)
    rospy.spin()




  def heartbeat_call(self, event):
    # Send a packet to every WiFiTrilat server.
    for host in [s[1:s.find('/WiFi')] for s in self.client.discover()]:
      send(IP(dst=host)/ICMP(), iface=self.interface)


  def connectToNet(self, essid, psswd, ip, nm):
    rospy.loginfo("Attempting to manually connect...")
    cli.execute_shell("wpa_supplicant -B -i %s -c <(wpa_passphrase %s \"%s\")" % (self.interface, essid, psswd))
    cli.execute_shell("ifconfig %s %s netmask %s" % (self.interface, ip, nm))




  def siglevel(self, packet):
    return -(256-ord(packet.notdecoded[-4:-3]))


if __name__ == "__main__":
  WiFiTrilatSrv(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6])
