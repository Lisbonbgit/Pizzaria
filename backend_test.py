#!/usr/bin/env python3
"""
Backend API Testing Suite for Pizza Ordering System
Tests all CRUD operations, authentication, and business logic
"""

import requests
import sys
import json
from datetime import datetime

class PizzariaAPITester:
    def __init__(self, base_url="https://order-print-1.preview.emergentagent.com"):
        self.base_url = base_url
        self.token = None
        self.tests_run = 0
        self.tests_passed = 0
        self.test_results = []

    def run_test(self, name, method, endpoint, expected_status, data=None, headers=None):
        """Run a single API test"""
        url = f"{self.base_url}/{endpoint}"
        test_headers = {'Content-Type': 'application/json'}
        
        # Add auth token if available and not explicitly overridden
        if self.token and (headers is None or 'Authorization' not in headers):
            test_headers['Authorization'] = f'Bearer {self.token}'
        
        if headers:
            test_headers.update(headers)

        self.tests_run += 1
        print(f"\n🔍 Testing {name}...")
        print(f"   URL: {url}")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=test_headers, timeout=30)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=test_headers, timeout=30)
            elif method == 'PUT':
                response = requests.put(url, json=data, headers=test_headers, timeout=30)
            elif method == 'DELETE':
                response = requests.delete(url, headers=test_headers, timeout=30)

            success = response.status_code == expected_status
            result_data = {}
            
            try:
                result_data = response.json() if response.text else {}
            except json.JSONDecodeError:
                result_data = {"raw_response": response.text}

            if success:
                self.tests_passed += 1
                print(f"✅ Passed - Status: {response.status_code}")
                if result_data:
                    print(f"   Response keys: {list(result_data.keys()) if isinstance(result_data, dict) else 'List response'}")
            else:
                print(f"❌ Failed - Expected {expected_status}, got {response.status_code}")
                print(f"   Response: {result_data}")

            # Store test result
            self.test_results.append({
                "name": name,
                "method": method,
                "endpoint": endpoint,
                "expected_status": expected_status,
                "actual_status": response.status_code,
                "success": success,
                "response_data": result_data
            })

            return success, result_data

        except requests.exceptions.Timeout:
            print(f"❌ Failed - Timeout after 30 seconds")
            self.test_results.append({
                "name": name,
                "success": False,
                "error": "Timeout"
            })
            return False, {}
        except Exception as e:
            print(f"❌ Failed - Error: {str(e)}")
            self.test_results.append({
                "name": name,
                "success": False,
                "error": str(e)
            })
            return False, {}

    def test_seed_database(self):
        """Initialize database with sample data"""
        print("🌱 Seeding database...")
        success, response = self.run_test(
            "Seed Database",
            "POST",
            "api/seed",
            200
        )
        return success

    def test_categories_list(self):
        """Test listing categories"""
        success, response = self.run_test(
            "List Categories", 
            "GET",
            "api/categories",
            200
        )
        
        if success and isinstance(response, list):
            print(f"   Found {len(response)} categories")
            expected_categories = ["Pizzas", "Bebidas", "Entradas", "Sobremesas"]
            found_categories = [cat.get('name') for cat in response if cat.get('name')]
            print(f"   Categories: {found_categories}")
            
            # Check if we have the expected categories
            for cat in expected_categories:
                if cat not in found_categories:
                    print(f"   ⚠️  Missing expected category: {cat}")
        
        return success

    def test_products_list(self):
        """Test listing products"""
        success, response = self.run_test(
            "List Products",
            "GET", 
            "api/products",
            200
        )
        
        if success and isinstance(response, list):
            print(f"   Found {len(response)} products")
            featured_count = sum(1 for p in response if p.get('featured', False))
            print(f"   Featured products: {featured_count}")
            
            # Check some expected products
            product_names = [p.get('name') for p in response if p.get('name')]
            expected_products = ["Margherita", "Pepperoni", "Coca-Cola", "Tiramisù"]
            
            for product in expected_products:
                if product in product_names:
                    print(f"   ✅ Found expected product: {product}")
                else:
                    print(f"   ⚠️  Missing expected product: {product}")
        
        return success

    def test_tables_list(self):
        """Test listing tables"""
        success, response = self.run_test(
            "List Tables",
            "GET",
            "api/tables", 
            200
        )
        
        if success and isinstance(response, list):
            print(f"   Found {len(response)} tables")
            table_numbers = [t.get('number') for t in response if t.get('number')]
            print(f"   Table numbers: {sorted(table_numbers)}")
            
            # Should have tables 1-10
            expected_tables = list(range(1, 11))
            missing_tables = [t for t in expected_tables if t not in table_numbers]
            if missing_tables:
                print(f"   ⚠️  Missing tables: {missing_tables}")
        
        return success

    def test_admin_login(self):
        """Test admin login with demo credentials"""
        success, response = self.run_test(
            "Admin Login",
            "POST",
            "api/auth/login",
            200,
            data={"email": "admin@pizzaria.pt", "password": "admin123"}
        )
        
        if success and response.get('access_token'):
            self.token = response['access_token']
            user = response.get('user', {})
            print(f"   ✅ Login successful for: {user.get('email')}")
            print(f"   User name: {user.get('name')}")
            return True
        else:
            print(f"   ❌ Login failed - no access token received")
            return False

    def test_admin_dashboard_stats(self):
        """Test dashboard statistics (requires auth)"""
        if not self.token:
            print("   ⚠️  Skipping - no auth token")
            return False
            
        success, response = self.run_test(
            "Dashboard Stats",
            "GET",
            "api/dashboard/stats",
            200
        )
        
        if success:
            stats = response
            print(f"   Orders today: {stats.get('total_orders_today', 0)}")
            print(f"   Revenue today: €{stats.get('total_revenue_today', 0)}")
            print(f"   Orders by status: {stats.get('orders_by_status', {})}")
            
        return success

    def test_table_by_number(self):
        """Test getting table by number (for QR code functionality)"""
        success, response = self.run_test(
            "Get Table by Number",
            "GET", 
            "api/tables/by-number/1",
            200
        )
        
        if success and response.get('number') == 1:
            print(f"   ✅ Found table: {response.get('name')} (ID: {response.get('id')})")
            return True
        
        return success

    def test_create_order(self):
        """Test creating an order"""
        # First get a table and some products
        tables_success, tables = self.run_test("Get Tables for Order", "GET", "api/tables", 200)
        products_success, products = self.run_test("Get Products for Order", "GET", "api/products", 200)
        
        if not (tables_success and products_success and tables and products):
            print("   ❌ Cannot create order - missing tables or products")
            return False
        
        table = tables[0] if tables else None
        product = products[0] if products else None
        
        if not table or not product:
            print("   ❌ Cannot create order - no valid table or product")
            return False
        
        order_data = {
            "table_id": table['id'],
            "table_number": table['number'],
            "items": [{
                "product_id": product['id'],
                "product_name": product['name'],
                "quantity": 1,
                "variation": None,
                "extras": [],
                "notes": "Test order",
                "unit_price": product['base_price'],
                "total_price": product['base_price']
            }],
            "notes": "Test order from API testing",
            "total": product['base_price']
        }
        
        success, response = self.run_test(
            "Create Order",
            "POST",
            "api/orders",
            200,
            data=order_data
        )
        
        if success and response.get('id'):
            print(f"   ✅ Order created: #{response.get('order_number')} (ID: {response.get('id')})")
            print(f"   Table: {response.get('table_number')}")
            print(f"   Total: €{response.get('total')}")
            print(f"   Status: {response.get('status')}")
            return response.get('id')
        
        return None

    def test_invalid_login(self):
        """Test login with invalid credentials"""
        success, response = self.run_test(
            "Invalid Login Test",
            "POST", 
            "api/auth/login",
            401,
            data={"email": "wrong@email.com", "password": "wrongpassword"}
        )
        return success

    def test_categories_active_only(self):
        """Test filtering active categories only"""
        success, response = self.run_test(
            "List Active Categories Only",
            "GET",
            "api/categories?active_only=true",
            200
        )
        
        if success and isinstance(response, list):
            active_count = len([c for c in response if c.get('active', False)])
            print(f"   Active categories: {active_count}/{len(response)}")
        
        return success

    def test_products_available_only(self):
        """Test filtering available products only"""  
        success, response = self.run_test(
            "List Available Products Only",
            "GET",
            "api/products?available_only=true", 
            200
        )
        
        if success and isinstance(response, list):
            available_count = len([p for p in response if p.get('available', False)])
            print(f"   Available products: {available_count}/{len(response)}")
        
        return success

def main():
    print("🍕 Pizzaria API Backend Testing")
    print("=" * 50)
    
    tester = PizzariaAPITester()
    
    # Core functionality tests
    print("\n📊 CORE API TESTS")
    print("-" * 30)
    
    # Seed database first (may already be seeded)
    tester.test_seed_database()
    
    # Test public endpoints (no auth required)
    tester.test_categories_list()
    tester.test_products_list() 
    tester.test_tables_list()
    tester.test_table_by_number()
    tester.test_categories_active_only()
    tester.test_products_available_only()
    
    print("\n🔐 AUTHENTICATION TESTS")
    print("-" * 30)
    
    # Test authentication
    tester.test_invalid_login()
    login_success = tester.test_admin_login()
    
    if login_success:
        print("\n👨‍💼 ADMIN-ONLY TESTS")
        print("-" * 30)
        
        # Test admin endpoints
        tester.test_admin_dashboard_stats()
        
        print("\n🛒 ORDER WORKFLOW TESTS")
        print("-" * 30)
        
        # Test order creation
        order_id = tester.test_create_order()
        
    else:
        print("   ⚠️  Skipping admin tests - login failed")

    # Print summary
    print("\n" + "=" * 50)
    print("📊 TEST RESULTS SUMMARY")
    print(f"   Tests run: {tester.tests_run}")
    print(f"   Tests passed: {tester.tests_passed}")
    print(f"   Success rate: {(tester.tests_passed/tester.tests_run*100):.1f}%" if tester.tests_run > 0 else "0%")
    
    # Detailed failures
    failures = [t for t in tester.test_results if not t.get('success', False)]
    if failures:
        print(f"\n❌ FAILED TESTS ({len(failures)}):")
        for failure in failures:
            print(f"   • {failure['name']}")
            if 'error' in failure:
                print(f"     Error: {failure['error']}")
            elif 'actual_status' in failure:
                print(f"     Expected: {failure['expected_status']}, Got: {failure['actual_status']}")
    
    print("\n✅ Backend API testing complete!")
    
    # Return exit code
    return 0 if tester.tests_passed == tester.tests_run else 1

if __name__ == "__main__":
    sys.exit(main())