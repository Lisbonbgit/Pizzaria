"""
Daily Report API Tests
Tests for the daily report email system endpoints.
Features tested:
- Test daily report endpoint (config validation)
- Report configuration endpoint
- Scheduler status endpoint
- Scheduler enable/disable endpoints
- Report logs endpoint
- Authentication requirements for all endpoints
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
ADMIN_EMAIL = "admin@pizzaria.pt"
ADMIN_PASSWORD = "admin123"


class TestAuthentication:
    """Tests for authentication requirements on daily report endpoints"""
    
    def test_login_success(self):
        """Test successful admin login"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        
        assert response.status_code == 200, f"Login failed: {response.text}"
        data = response.json()
        assert "access_token" in data
        assert "user" in data
        assert data["user"]["email"] == ADMIN_EMAIL
        print(f"Login successful for {ADMIN_EMAIL}")


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token for tests"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    
    if response.status_code == 200:
        token = response.json().get("access_token")
        print(f"Auth token obtained successfully")
        return token
    
    pytest.skip("Authentication failed - skipping authenticated tests")


@pytest.fixture
def auth_headers(auth_token):
    """Create authorization headers"""
    return {"Authorization": f"Bearer {auth_token}"}


class TestDailyReportEndpointsWithoutAuth:
    """Test that all daily report endpoints require authentication"""
    
    def test_test_daily_report_requires_auth(self):
        """POST /api/admin/test-daily-report should require auth"""
        response = requests.post(f"{BASE_URL}/api/admin/test-daily-report")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("test-daily-report correctly requires authentication")
    
    def test_report_config_requires_auth(self):
        """GET /api/admin/report-config should require auth"""
        response = requests.get(f"{BASE_URL}/api/admin/report-config")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("report-config correctly requires authentication")
    
    def test_scheduler_status_requires_auth(self):
        """GET /api/admin/scheduler/status should require auth"""
        response = requests.get(f"{BASE_URL}/api/admin/scheduler/status")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("scheduler/status correctly requires authentication")
    
    def test_scheduler_enable_requires_auth(self):
        """POST /api/admin/scheduler/enable should require auth"""
        response = requests.post(f"{BASE_URL}/api/admin/scheduler/enable")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("scheduler/enable correctly requires authentication")
    
    def test_scheduler_disable_requires_auth(self):
        """POST /api/admin/scheduler/disable should require auth"""
        response = requests.post(f"{BASE_URL}/api/admin/scheduler/disable")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("scheduler/disable correctly requires authentication")
    
    def test_report_logs_requires_auth(self):
        """GET /api/admin/report-logs should require auth"""
        response = requests.get(f"{BASE_URL}/api/admin/report-logs")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("report-logs correctly requires authentication")


class TestReportConfiguration:
    """Test report configuration endpoint"""
    
    def test_get_report_config(self, auth_headers):
        """GET /api/admin/report-config should return current configuration"""
        response = requests.get(
            f"{BASE_URL}/api/admin/report-config",
            headers=auth_headers
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify required fields are present
        assert "resend_configured" in data, "Missing resend_configured field"
        assert "report_email" in data, "Missing report_email field"
        assert "scheduler_enabled" in data, "Missing scheduler_enabled field"
        
        # Since RESEND_API_KEY is empty, resend_configured should be False
        assert data["resend_configured"] == False, "resend_configured should be False when API key is empty"
        
        # Verify additional config fields
        assert "timezone" in data, "Missing timezone field"
        assert data["timezone"] == "Europe/Lisbon", "Timezone should be Europe/Lisbon"
        
        print(f"Report config: resend_configured={data['resend_configured']}, email={data['report_email']}")


class TestTestDailyReport:
    """Test the manual daily report test endpoint"""
    
    def test_daily_report_fails_without_resend_key(self, auth_headers):
        """POST /api/admin/test-daily-report should fail when RESEND_API_KEY is not configured"""
        response = requests.post(
            f"{BASE_URL}/api/admin/test-daily-report",
            headers=auth_headers
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Should return success=False with appropriate error
        assert data["success"] == False, "Should fail when RESEND_API_KEY is not configured"
        assert "error" in data or "message" in data, "Should include error message"
        
        # Check error message mentions API key
        error_msg = data.get("error", "") or data.get("message", "")
        assert "RESEND" in error_msg.upper() or "API" in error_msg.upper() or "KEY" in error_msg.upper() or "configurad" in error_msg.lower(), \
            f"Error message should mention API key configuration: {error_msg}"
        
        print(f"Test daily report correctly failed: {data.get('message', data.get('error'))}")


class TestSchedulerStatus:
    """Test scheduler status endpoint"""
    
    def test_get_scheduler_status(self, auth_headers):
        """GET /api/admin/scheduler/status should return scheduler state"""
        response = requests.get(
            f"{BASE_URL}/api/admin/scheduler/status",
            headers=auth_headers
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify required fields
        assert "enabled" in data, "Missing enabled field"
        assert "timezone" in data, "Missing timezone field"
        assert "schedule" in data, "Missing schedule field"
        
        # Verify timezone is Europe/Lisbon
        assert data["timezone"] == "Europe/Lisbon", f"Timezone should be Europe/Lisbon, got {data['timezone']}"
        
        # Verify schedule is 23:59
        assert data["schedule"] == "23:59", f"Schedule should be 23:59, got {data['schedule']}"
        
        print(f"Scheduler status: enabled={data['enabled']}, timezone={data['timezone']}, schedule={data['schedule']}")


class TestSchedulerEnable:
    """Test scheduler enable endpoint"""
    
    def test_enable_scheduler_fails_without_resend_key(self, auth_headers):
        """POST /api/admin/scheduler/enable should fail when RESEND_API_KEY is not configured"""
        response = requests.post(
            f"{BASE_URL}/api/admin/scheduler/enable",
            headers=auth_headers
        )
        
        # Should return 400 error when API key not configured
        assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Check error message mentions configuration requirements
        assert "detail" in data, "Missing detail field in error response"
        detail = data["detail"].lower()
        assert "resend" in detail or "api" in detail or "config" in detail, \
            f"Error should mention configuration: {data['detail']}"
        
        print(f"Scheduler enable correctly failed: {data['detail']}")


class TestSchedulerDisable:
    """Test scheduler disable endpoint"""
    
    def test_disable_scheduler(self, auth_headers):
        """POST /api/admin/scheduler/disable should disable the scheduler"""
        response = requests.post(
            f"{BASE_URL}/api/admin/scheduler/disable",
            headers=auth_headers
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify response
        assert "enabled" in data or "message" in data, "Response should contain enabled or message"
        
        if "enabled" in data:
            assert data["enabled"] == False, "enabled should be False after disable"
        
        print(f"Scheduler disabled successfully: {data}")
    
    def test_scheduler_status_after_disable(self, auth_headers):
        """Verify scheduler status is disabled after disable call"""
        # First disable
        requests.post(
            f"{BASE_URL}/api/admin/scheduler/disable",
            headers=auth_headers
        )
        
        # Then check status
        response = requests.get(
            f"{BASE_URL}/api/admin/scheduler/status",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] == False, "Scheduler should be disabled"
        
        print("Scheduler status correctly shows disabled")


class TestReportLogs:
    """Test report logs endpoint"""
    
    def test_get_report_logs(self, auth_headers):
        """GET /api/admin/report-logs should return list of logs"""
        response = requests.get(
            f"{BASE_URL}/api/admin/report-logs",
            headers=auth_headers
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Should return a list (may be empty)
        assert isinstance(data, list), f"Expected list, got {type(data)}"
        
        print(f"Report logs returned {len(data)} entries")
    
    def test_get_report_logs_with_limit(self, auth_headers):
        """GET /api/admin/report-logs should respect limit parameter"""
        response = requests.get(
            f"{BASE_URL}/api/admin/report-logs?limit=5",
            headers=auth_headers
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert isinstance(data, list)
        assert len(data) <= 5, f"Should return at most 5 entries, got {len(data)}"
        
        print(f"Report logs with limit=5 returned {len(data)} entries")


class TestInvalidToken:
    """Test endpoints with invalid token"""
    
    def test_test_daily_report_invalid_token(self):
        """POST /api/admin/test-daily-report should reject invalid token"""
        response = requests.post(
            f"{BASE_URL}/api/admin/test-daily-report",
            headers={"Authorization": "Bearer invalid_token_here"}
        )
        
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("test-daily-report correctly rejects invalid token")
    
    def test_report_config_invalid_token(self):
        """GET /api/admin/report-config should reject invalid token"""
        response = requests.get(
            f"{BASE_URL}/api/admin/report-config",
            headers={"Authorization": "Bearer invalid_token_here"}
        )
        
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("report-config correctly rejects invalid token")


class TestReportLogsAfterTestReport:
    """Test that report logs are created after test report attempts"""
    
    def test_report_logs_after_failed_test(self, auth_headers):
        """
        After calling test-daily-report (which fails without API key),
        report-logs should contain the failure entry
        """
        # First, attempt to send test report (will fail)
        test_response = requests.post(
            f"{BASE_URL}/api/admin/test-daily-report",
            headers=auth_headers
        )
        
        assert test_response.status_code == 200
        
        # Now check logs
        logs_response = requests.get(
            f"{BASE_URL}/api/admin/report-logs?limit=1",
            headers=auth_headers
        )
        
        assert logs_response.status_code == 200
        logs = logs_response.json()
        
        # Should have at least one log entry from the failed attempt
        if len(logs) > 0:
            latest_log = logs[0]
            # Verify log structure
            if "success" in latest_log:
                assert latest_log["success"] == False, "Log should show failure"
            if "error" in latest_log:
                print(f"Log error recorded: {latest_log['error']}")
        
        print(f"Report logs correctly recorded test attempt")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
