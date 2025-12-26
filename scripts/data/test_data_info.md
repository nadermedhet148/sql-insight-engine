

---

# E-Commerce Business Context

## Database Overview

Our e-commerce platform consists of three core entities:

### Users Table
Stores customer information including registration details and account status. Each user represents a customer who can place orders on the platform.

- **Key Fields**: `user_id`, `name`, `email`, `registration_date`
- **Business Significance**: Used to track customer lifetime value, registration trends, and user segmentation

### Products Table
Contains the catalog of items available for purchase. Each product has a unique SKU, pricing, and category classification.

- **Key Fields**: `product_id`, `sku`, `name`, `category`, `price`, `stock_quantity`
- **Business Significance**: Core inventory management, pricing strategy, and product performance analysis

### Orders Table
Records all customer transactions. Each order links a user to a product with quantity and timestamp information.

- **Key Fields**: `order_id`, `user_id` (FK), `product_id` (FK), `quantity`, `order_date`
- **Business Significance**: Revenue tracking, sales analytics, and customer purchase behavior

---

## E-Commerce Business Terminology

### Revenue Metrics
- **GMV (Gross Merchandise Value)**: Total sales dollar value before any deductions. Calculated as `SUM(quantity * price)`
- **AOV (Average Order Value)**: Average revenue per order. Calculated as `Total Revenue / Number of Orders`
- **ARPU (Average Revenue Per User)**: Average revenue generated per customer. Calculated as `Total Revenue / Number of Users`
- **Revenue**: Total sales amount. Synonym for GMV in our context.

### Customer Metrics
- **New Customers**: Users who registered within a specific time period
- **Active Customers**: Users who have placed at least one order
- **Customer Acquisition**: The number of new users registered in a period
- **Repeat Customer Rate**: Percentage of customers who made more than one purchase
- **Customer Lifetime Value (CLV)**: Total revenue expected from a customer over their lifetime

### Product Metrics
- **Best Sellers**: Products with the highest sales volume or revenue
- **Top Products**: Same as best sellers
- **Product Performance**: Sales metrics grouped by product
- **Category Performance**: Aggregated sales by product category
- **SKU**: Stock Keeping Unit - unique identifier for each product
- **Inventory Turnover**: Rate at which inventory is sold and replaced

### Order Metrics
- **Order Volume**: Total number of orders placed
- **Order Frequency**: How often customers place orders
- **Cart Size**: Average number of items (quantity) per order
- **Conversion Rate**: Percentage of users who have made a purchase

### Time-Based Analysis
- **Daily Sales**: Aggregated sales data by day
- **Monthly Revenue**: Revenue totals grouped by month
- **Yearly Trends**: Year-over-year growth analysis
- **Seasonality**: Patterns in sales tied to specific times of year
- **Peak Hours/Days**: Time periods with highest order volume

---

## Common Business Reports & Queries

### 1. Sales Performance Reports

**Daily Sales Report**
- Purpose: Track daily revenue and order volume
- Typical Questions:
  - "What was yesterday's total revenue?"
  - "How many orders did we receive today?"
  - "Show me daily sales for the last 30 days"

**Monthly Revenue Analysis**
- Purpose: Understand revenue trends and growth
- Typical Questions:
  - "What was our monthly revenue for Q4?"
  - "Compare this month's sales to last month"
  - "Which month had the highest revenue this year?"

**Year-over-Year Growth**
- Purpose: Measure business growth and trends
- Typical Questions:
  - "What's our year-over-year revenue growth?"
  - "Compare this year's sales to last year"

### 2. Product Analytics Reports

**Top Selling Products**
- Purpose: Identify best performers and inventory priorities
- Typical Questions:
  - "What are the top 10 best-selling products?"
  - "Which products generated the most revenue last month?"
  - "Show me the least popular products"

**Category Performance**
- Purpose: Understand which product categories drive sales
- Typical Questions:
  - "What is the revenue breakdown by category?"
  - "Which category has the most orders?"
  - "Compare Electronics vs Clothing sales"

**Inventory Insights**
- Purpose: Manage stock levels and identify potential issues
- Typical Questions:
  - "Which products are low in stock?"
  - "Show me products with stock below 100 units"
  - "What's the average inventory level by category?"

### 3. Customer Analytics Reports

**Customer Acquisition**
- Purpose: Track growth in customer base
- Typical Questions:
  - "How many new customers registered this month?"
  - "What's our monthly customer acquisition trend?"
  - "Compare new registrations year-over-year"

**Customer Purchase Behavior**
- Purpose: Understand buying patterns and engagement
- Typical Questions:
  - "How many customers have made more than 5 orders?"
  - "What's the average number of orders per customer?"
  - "Who are our top 20 customers by spending?"

**Customer Lifetime Value**
- Purpose: Identify most valuable customers
- Typical Questions:
  - "What's the total spending per customer?"
  - "Show me customers who spent more than $10,000"
  - "What's the average lifetime value of our customers?"

**Active vs Inactive Users**
- Purpose: Measure engagement and retention
- Typical Questions:
  - "How many registered users have never placed an order?"
  - "What percentage of users are active buyers?"
  - "Who hasn't purchased in the last 6 months?"

### 4. Operational Reports

**Order Fulfillment Metrics**
- Purpose: Monitor order processing and efficiency
- Typical Questions:
  - "How many orders were placed in the last hour?"
  - "What's the average order size (quantity)?"
  - "Show me large orders (>10 items)"

**Revenue Attribution**
- Purpose: Understand where revenue comes from
- Typical Questions:
  - "What percentage of revenue comes from repeat customers?"
  - "How much revenue did new customers generate this quarter?"
  - "Break down revenue by customer segment"

---

## Business Logic Guidelines

### Calculation Standards

**Revenue Calculation**
Always calculate revenue as: `quantity * product_price`
- Join orders with products to get current prices
- Note: Historical orders use current product prices (price changes are not tracked)

**Date Filtering**
- "Last month" = previous calendar month (e.g., if today is Jan 15, last month = December)
- "This month" = current calendar month to date
- "Last 30 days" = rolling 30-day window from today
- "YTD" (Year to Date) = January 1 of current year to today

**Customer Classification**
- **New Customer**: Registered within the specified time period
- **Active Customer**: Has placed at least 1 order (ever)
- **Repeat Customer**: Has placed more than 1 order
- **VIP Customer**: Total lifetime spending > $5,000 OR total orders > 20

**Product Classification**
- **Low Stock**: stock_quantity < 100 units
- **Out of Stock**: stock_quantity = 0
- **High Demand**: Products with >100 orders in the last 30 days

### Common Aggregations

**By Time Period**
- Group by DATE(order_date) for daily reports
- Use DATE_TRUNC('month', order_date) for monthly reports
- EXTRACT(YEAR from order_date) for yearly analysis

**By Product**
- Always include product name and category in product reports
- Sort by revenue or quantity depending on context

**By Customer**
- Include customer name and email in customer reports
- Respect privacy - don't expose sensitive data in public reports

---

## Query Optimization Tips

### Performance Considerations

**Large Dataset Queries**
- Our orders table contains 1,000,000+ records
- Always use indexed columns (user_id, product_id, order_date) in WHERE clauses
- Limit results when showing top N records
- Use date ranges to reduce scan size

**Common Query Patterns**

1. **Revenue Queries**: Always join orders → products to get prices
2. **Customer Analytics**: Join orders → users to get customer details
3. **Product Rankings**: Use ORDER BY with LIMIT for top N
4. **Time Series**: Group by date fields with appropriate date functions

### Example Business Questions

**Executive Dashboard**
- "What's our total revenue this month?"
- "How many active customers do we have?"
- "What's today's order count?"

**Marketing Team**
- "Which customers spent more than $1,000 last quarter?"
- "What's our customer retention rate?"
- "Show me new customers from the last week"

**Product Team**
- "What are the top 5 products by revenue?"
- "Which categories are underperforming?"
- "Show me products that need restocking"

**Finance Team**
- "What's our daily revenue trend for the last 90 days?"
- "Calculate AOV for each month this year"
- "What's the revenue breakdown by product category?"

---

## Data Quality Notes

### Known Data Characteristics

- All dates are stored in UTC timezone
- Product prices are in USD
- Stock quantities are updated in near real-time
- Order quantities are always positive integers
- User emails are unique and validated
- Product SKUs follow format: `SKU-XXXXX` (5 digits)

### Missing or Null Values

- Some users may not have orders (inactive customers)
- All products should have positive prices
- Stock quantities of 0 indicate out-of-stock items
- No null values expected in critical fields (order_id, user_id, product_id)


