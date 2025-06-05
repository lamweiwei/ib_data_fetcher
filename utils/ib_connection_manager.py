"""
Interactive Brokers connection management utilities.

This module handles IB API connection management functionality that was previously
embedded in fetcher.py, following the principle of keeping files under 300 lines
and avoiding code duplication.
"""

import asyncio
import time
from typing import Dict, Optional

from ib_async import IB

from utils.logging import get_logger


class IBConnectionManager:
    """Manages IB API connections with watchdog and heartbeat monitoring."""
    
    def __init__(self, config: Dict):
        """
        Initialize the connection manager.
        
        Args:
            config: Configuration dictionary containing connection settings
        """
        self.config = config
        self.logger = get_logger(__name__)
        self.ib = IB()
        
        # Connection state
        self.is_connected = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = self.config.get('connection', {}).get('reconnection_attempts', 3)
        
        # Monitoring tasks
        self.watchdog_task: Optional[asyncio.Task] = None
        self.heartbeat_task: Optional[asyncio.Task] = None
    
    async def connect(self) -> bool:
        """
        Establish connection to IB TWS/Gateway with error handling.
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            connection_config = self.config['connection']
            
            self.logger.info(
                "Connecting to IB TWS at %s:%d (client_id=%d)",
                connection_config['host'],
                connection_config['port'],
                connection_config['client_id']
            )
            
            await self.ib.connectAsync(
                host=connection_config['host'],
                port=connection_config['port'],
                clientId=connection_config['client_id'],
                timeout=connection_config['timeout']
            )
            
            self.is_connected = True
            self.reconnect_attempts = 0
            
            # Start monitoring tasks
            await self._start_monitoring_tasks()
            
            self.logger.info("Successfully connected to IB TWS")
            return True
            
        except Exception as e:
            self.logger.error("Failed to connect to IB TWS: %s", e)
            self.is_connected = False
            return False
    
    async def disconnect(self):
        """Disconnect from IB TWS and cleanup tasks."""
        try:
            # Stop monitoring tasks
            if self.watchdog_task and not self.watchdog_task.done():
                self.watchdog_task.cancel()
                try:
                    await self.watchdog_task
                except asyncio.CancelledError:
                    pass
            
            if self.heartbeat_task and not self.heartbeat_task.done():
                self.heartbeat_task.cancel()
                try:
                    await self.heartbeat_task
                except asyncio.CancelledError:
                    pass
            
            # Disconnect from IB
            if self.ib.isConnected():
                self.ib.disconnect()
            
            self.is_connected = False
            self.logger.info("Disconnected from IB TWS")
            
        except Exception as e:
            self.logger.error("Error during disconnect: %s", e)
    
    async def _start_monitoring_tasks(self):
        """Start connection monitoring tasks."""
        self.watchdog_task = asyncio.create_task(self._connection_watchdog())
        self.heartbeat_task = asyncio.create_task(self._heartbeat_monitor())
    
    async def _connection_watchdog(self):
        """
        Monitor connection health every 30 seconds.
        Auto-reconnects if connection is lost.
        """
        while True:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds
                
                if not self.ib.isConnected():
                    self.logger.warning("Connection lost, attempting reconnection")
                    self.is_connected = False
                    
                    if await self._auto_reconnect():
                        self.logger.info("Auto-reconnection successful")
                    else:
                        self.logger.error("Auto-reconnection failed")
                        break
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in connection watchdog: %s", e)
    
    async def _heartbeat_monitor(self):
        """
        Send heartbeat pings every 15 seconds.
        Consider connection dead after 45s no response.
        """
        while True:
            try:
                await asyncio.sleep(15)  # Ping every 15 seconds
                
                if self.ib.isConnected():
                    # Simple check - request current time
                    start_time = time.time()
                    try:
                        await asyncio.wait_for(
                            self.ib.reqCurrentTimeAsync(),
                            timeout=45  # 45s timeout
                        )
                        elapsed = time.time() - start_time
                        self.logger.debug("Heartbeat successful (%.2fs)", elapsed)
                    except asyncio.TimeoutError:
                        self.logger.warning("Heartbeat timeout - connection may be dead")
                        self.is_connected = False
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.debug("Heartbeat error (non-critical): %s", e)
    
    async def _auto_reconnect(self) -> bool:
        """
        Attempt to reconnect with exponential backoff.
        
        Returns:
            bool: True if reconnection successful
        """
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            self.logger.error("Max reconnection attempts reached")
            return False
        
        self.reconnect_attempts += 1
        
        # Exponential backoff: 30s → 60s → 120s
        wait_time = 30 * (2 ** (self.reconnect_attempts - 1))
        
        self.logger.info(
            "Reconnection attempt %d/%d in %ds",
            self.reconnect_attempts,
            self.max_reconnect_attempts,
            wait_time
        )
        
        await asyncio.sleep(wait_time)
        
        # Disconnect first if still connected
        if self.ib.isConnected():
            self.ib.disconnect()
        
        return await self.connect()
    
    def get_ib_client(self) -> IB:
        """
        Get the underlying IB client for making API calls.
        
        Returns:
            IB: The IB client instance
        """
        return self.ib 