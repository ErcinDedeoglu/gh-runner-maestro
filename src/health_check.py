#!/usr/bin/env python3
"""
Health check script for gh-runner-maestro
Provides detailed health status and monitoring capabilities
"""

import os
import sys
import json
import time
import logging
import docker
from datetime import datetime
from typing import Dict, Any, List

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class HealthChecker:
    def __init__(self):
        self.docker_client = docker.from_env()
        
    def check_docker_daemon(self) -> Dict[str, Any]:
        """Check Docker daemon connectivity"""
        try:
            self.docker_client.ping()
            return {
                "status": "healthy",
                "message": "Docker daemon is responsive"
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "message": f"Docker daemon error: {str(e)}"
            }
    
    def check_container_health(self) -> Dict[str, Any]:
        """Check health of managed containers"""
        try:
            containers = self.docker_client.containers.list(all=True)
            managed_containers = [
                c for c in containers 
                if c.labels.get("maestro.managed") == "true"
            ]
            
            stats = {
                "total": len(managed_containers),
                "running": 0,
                "healthy": 0,
                "unhealthy": 0,
                "exited": 0,
                "restarting": 0
            }
            
            for container in managed_containers:
                status = container.status
                stats[status] = stats.get(status, 0) + 1
                
                # Check health status if available
                health_status = container.attrs.get('State', {}).get('Health', {}).get('Status')
                if health_status == 'healthy':
                    stats['healthy'] += 1
                elif health_status == 'unhealthy':
                    stats['unhealthy'] += 1
            
            return {
                "status": "healthy" if stats["running"] > 0 else "unhealthy",
                "details": stats,
                "containers": [
                    {
                        "name": c.name,
                        "status": c.status,
                        "image": c.image.tags[0] if c.image.tags else c.image.id[:12],
                        "created": c.attrs.get("Created", ""),
                        "health": c.attrs.get('State', {}).get('Health', {}).get('Status', 'unknown')
                    }
                    for c in managed_containers
                ]
            }
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "message": f"Container health check failed: {str(e)}"
            }
    
    def check_disk_space(self) -> Dict[str, Any]:
        """Check available disk space"""
        try:
            import shutil
            total, used, free = shutil.disk_usage("/")
            free_percent = (free / total) * 100
            
            return {
                "status": "healthy" if free_percent > 10 else "warning",
                "details": {
                    "total_gb": round(total / (1024**3), 2),
                    "used_gb": round(used / (1024**3), 2),
                    "free_gb": round(free / (1024**3), 2),
                    "free_percent": round(free_percent, 2)
                }
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "message": f"Disk space check failed: {str(e)}"
            }
    
    def check_memory_usage(self) -> Dict[str, Any]:
        """Check memory usage"""
        try:
            with open('/proc/meminfo', 'r') as f:
                meminfo = f.read()
            
            # Parse memory info
            mem_total = int([line for line in meminfo.split('\n') if 'MemTotal:' in line][0].split()[1]) * 1024
            mem_available = int([line for line in meminfo.split('\n') if 'MemAvailable:' in line][0].split()[1]) * 1024
            
            used_percent = ((mem_total - mem_available) / mem_total) * 100
            
            return {
                "status": "healthy" if used_percent < 90 else "warning",
                "details": {
                    "total_mb": round(mem_total / (1024**2), 2),
                    "available_mb": round(mem_available / (1024**2), 2),
                    "used_percent": round(used_percent, 2)
                }
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "message": f"Memory check failed: {str(e)}"
            }
    
    def check_github_connectivity(self) -> Dict[str, Any]:
        """Check GitHub API connectivity"""
        try:
            import urllib.request
            import urllib.error
            
            # Simple connectivity check
            response = urllib.request.urlopen('https://api.github.com', timeout=10)
            return {
                "status": "healthy",
                "message": "GitHub API is reachable",
                "response_time_ms": 0
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "message": f"GitHub API connectivity failed: {str(e)}"
            }
    
    def run_full_health_check(self) -> Dict[str, Any]:
        """Run comprehensive health check"""
        checks = {
            "timestamp": datetime.utcnow().isoformat(),
            "docker_daemon": self.check_docker_daemon(),
            "containers": self.check_container_health(),
            "disk_space": self.check_disk_space(),
            "memory": self.check_memory_usage(),
            "github_connectivity": self.check_github_connectivity()
        }
        
        # Overall status
        failed_checks = [
            name for name, check in checks.items() 
            if name != "timestamp" and check.get("status") == "unhealthy"
        ]
        
        if failed_checks:
            checks["overall_status"] = "unhealthy"
            checks["failed_checks"] = failed_checks
        else:
            checks["overall_status"] = "healthy"
        
        return checks
    
    def monitor_continuous(self, interval: int = 30):
        """Continuous monitoring mode"""
        logger.info(f"Starting continuous health monitoring (interval: {interval}s)")
        
        while True:
            try:
                health = self.run_full_health_check()
                
                # Log health status
                if health["overall_status"] == "healthy":
                    logger.info("Health check: OK")
                else:
                    logger.warning(f"Health check: FAILED - {health.get('failed_checks', [])}")
                
                # Output JSON for external monitoring
                print(json.dumps(health, indent=2))
                
                time.sleep(interval)
                
            except KeyboardInterrupt:
                logger.info("Monitoring stopped by user")
                break
            except Exception as e:
                logger.error(f"Monitoring error: {e}")
                time.sleep(interval)

def main():
    """Main health check entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Health check for gh-runner-maestro")
    parser.add_argument("--continuous", "-c", action="store_true", 
                        help="Run continuous monitoring")
    parser.add_argument("--interval", "-i", type=int, default=30,
                        help="Monitoring interval in seconds")
    parser.add_argument("--json", "-j", action="store_true",
                        help="Output as JSON")
    
    args = parser.parse_args()
    
    checker = HealthChecker()
    
    if args.continuous:
        checker.monitor_continuous(args.interval)
    else:
        health = checker.run_full_health_check()
        
        if args.json:
            print(json.dumps(health, indent=2))
        else:
            print(f"Health Check Results - {health['timestamp']}")
            print("=" * 50)
            print(f"Overall Status: {health['overall_status'].upper()}")
            print()
            
            for check_name, check_result in health.items():
                if check_name not in ["timestamp", "overall_status", "failed_checks"]:
                    print(f"{check_name.replace('_', ' ').title()}: {check_result['status']}")
                    if "message" in check_result:
                        print(f"  {check_result['message']}")
                    if "details" in check_result:
                        print(f"  Details: {check_result['details']}")
                    print()
        
        # Exit with appropriate code
        sys.exit(0 if health["overall_status"] == "healthy" else 1)

if __name__ == "__main__":
    main()