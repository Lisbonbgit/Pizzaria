import React, { createContext, useContext, useState, useEffect } from 'react';

const CartContext = createContext();

export const useCart = () => {
  const context = useContext(CartContext);
  if (!context) {
    throw new Error('useCart must be used within a CartProvider');
  }
  return context;
};

export const CartProvider = ({ children }) => {
  const [items, setItems] = useState([]);
  const [tableNumber, setTableNumber] = useState(null);
  const [tableId, setTableId] = useState(null);
  const [orderNotes, setOrderNotes] = useState('');

  // Load cart from session storage
  useEffect(() => {
    const savedCart = sessionStorage.getItem('cart');
    const savedTable = sessionStorage.getItem('tableNumber');
    const savedTableId = sessionStorage.getItem('tableId');
    
    if (savedCart) {
      try {
        setItems(JSON.parse(savedCart));
      } catch (e) {
        console.error('Error loading cart:', e);
      }
    }
    if (savedTable) {
      setTableNumber(parseInt(savedTable));
    }
    if (savedTableId) {
      setTableId(savedTableId);
    }
  }, []);

  // Save cart to session storage
  useEffect(() => {
    sessionStorage.setItem('cart', JSON.stringify(items));
  }, [items]);

  // Save table to session storage
  useEffect(() => {
    if (tableNumber !== null) {
      sessionStorage.setItem('tableNumber', tableNumber.toString());
    }
    if (tableId !== null) {
      sessionStorage.setItem('tableId', tableId);
    }
  }, [tableNumber, tableId]);

  const addItem = (product, quantity, variation, extras, notes, selectedComplements = [], selectedPreference = null, priceOverride = null) => {
    const compKey = selectedComplements.map(g => g.items.map(i => i.name).join(',')).join('|');
    const prefKey = selectedPreference || '';
    const itemId = `${product.id}-${variation?.name || 'base'}-${extras.map(e => e.name).join('-')}-${compKey}-${prefKey}`;

    // Calculate prices (priceOverride força um valor, ex.: €0 nos incluídos do rodízio)
    let unitPrice;
    if (priceOverride != null) {
      unitPrice = priceOverride;
    } else {
      unitPrice = variation?.price || product.base_price;
      unitPrice += extras.reduce((sum, e) => sum + e.price, 0);
      unitPrice += selectedComplements.reduce((sum, group) =>
        sum + group.items.reduce((gs, item) => gs + (item.price || 0), 0), 0);
    }
    const totalPrice = unitPrice * quantity;

    const newItem = {
      id: itemId,
      product_id: product.id,
      product_name: product.name,
      product_image: product.image_url,
      quantity,
      variation,
      extras,
      selected_complements: selectedComplements,
      selected_preference: selectedPreference,
      notes,
      unit_price: unitPrice,
      total_price: totalPrice,
      rodizio_included: priceOverride === 0
    };

    setItems(prevItems => {
      // Check if same item exists
      const existingIndex = prevItems.findIndex(item => item.id === itemId);
      
      if (existingIndex >= 0) {
        // Update quantity
        const updated = [...prevItems];
        updated[existingIndex].quantity += quantity;
        updated[existingIndex].total_price = updated[existingIndex].unit_price * updated[existingIndex].quantity;
        return updated;
      }
      
      return [...prevItems, newItem];
    });
  };

  const updateItemQuantity = (itemId, quantity) => {
    if (quantity <= 0) {
      removeItem(itemId);
      return;
    }

    setItems(prevItems => 
      prevItems.map(item => 
        item.id === itemId 
          ? { ...item, quantity, total_price: item.unit_price * quantity }
          : item
      )
    );
  };

  const removeItem = (itemId) => {
    setItems(prevItems => prevItems.filter(item => item.id !== itemId));
  };

  const clearCart = () => {
    setItems([]);
    setOrderNotes('');
    sessionStorage.removeItem('cart');
  };

  const getTotal = () => {
    return items.reduce((sum, item) => sum + item.total_price, 0);
  };

  const getItemCount = () => {
    return items.reduce((sum, item) => sum + item.quantity, 0);
  };

  const setTable = (number, id) => {
    setTableNumber(number);
    setTableId(id);
  };

  return (
    <CartContext.Provider value={{
      items,
      tableNumber,
      tableId,
      orderNotes,
      setOrderNotes,
      addItem,
      updateItemQuantity,
      removeItem,
      clearCart,
      getTotal,
      getItemCount,
      setTable
    }}>
      {children}
    </CartContext.Provider>
  );
};
